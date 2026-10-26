"""Small TDD gates over controller-owned jobs and current native run identities.

No worker-supplied pass flags or receipt imports. Store and Runner live only in
the controller; model output is limited to a review decision with findings.
"""
import json
import re
import difflib
from itertools import islice
from pathlib import Path
import tempfile
import time
from .artifacts import protected_unchanged
from .effects import Pending, EffectBlocked, Journal, write_json
from .executor import preview_drivers,validation_files

PROTECTED = ('.github/', 'pyproject.toml', 'pytest.ini', 'setup.cfg', 'tox.ini',
             'requirements.txt', 'package.json', 'package-lock.json')
REVIEW_FINDINGS_CONTRACT=('findings lists blocking defects only. approve requires findings=[]; '
    'put positive observations in reason. changes or escalate requires at least one concrete finding.')
CONTROL_CONTRACT = 2
CONTROL_REVIEW_CONTRACT=('Check approved acceptance coverage before approving tests. Every validated Red assertion failure is a mandatory '
    'mutation target. Passing auxiliary checks still run in the full suite. Add control_risks only for passing cases requiring '
    'an additional product negative control, with a concrete reason; never exclude a Red target. Request changes for missing or vacuous behavior tests '
    'or any Red failure that cannot be fixed by implementing product behavior with the tests/configuration unchanged.')


def suite_report(value,*,diagnostic=False):
    """Shared full-suite facts; caller must separately verify job provenance."""
    report=value.get('report')
    if (not isinstance(report,dict) or report.get('version')!=1
            or type(report.get('tests_run')) is not int or report['tests_run']<1
            or not isinstance(report.get('cases'),list)
            or report['tests_run']!=len(report['cases']) or len(set(report['cases']))!=len(report['cases'])
            or any(not isinstance(case,str) or not case for case in report['cases'])
            or any(not isinstance(report.get(field),list) for field in ('failures','errors','skips','expected_failures','unexpected_successes'))
            or not diagnostic and any(report[field] for field in ('errors','skips','expected_failures','unexpected_successes'))):
        raise ValueError('complete real suite without errors or skips required')
    failed={item['case'] for item in report['failures']}
    preview=report.get('qa_preview');preview_failed=False
    if value.get('identity',{}).get('qa_preview'):
        if (not isinstance(preview,dict) or preview.get('version')!=1
                or preview.get('source_sha')!=value['identity']['snapshot']
                or preview.get('status') not in ('passed','failed')
                or not isinstance(preview.get('checks'),list) or len(set(preview['checks']))!=len(preview['checks'])
                or not all(isinstance(key,str) and key for key in preview['checks'])
                or not isinstance(preview.get('errors'),list)
                or not all(isinstance(error,str) for error in preview['errors'])
                or (preview['status']=='passed')!= (not preview['errors'])):
            raise ValueError('complete snapshot-bound frozen QA preview required')
        preview_failed=preview['status']=='failed'
    if (not failed<=set(report['cases'])
            or any(not set(report[field])<=set(report['cases']) for field in ('errors','skips','expected_failures','unexpected_successes'))
            or value['exit_code']!=(1 if failed or report['errors'] or report['unexpected_successes'] or preview_failed else 0)):
        raise ValueError('suite exit and assertion facts disagree')
    if preview_failed and not diagnostic:raise ValueError('frozen QA preview failed: '+json.dumps(preview['errors'])[:1800])
    return report


def preview_evidence(project,store,value,snapshot,phase):
    """Do not let a historic Green/CI receipt silently satisfy a new contract."""
    bundle,_=validation_files(project,store)
    if value['identity'].get('validation_bundle')!=bundle:raise ValueError('exact installed validation bundle required')
    drivers=preview_drivers(project,phase,store)
    if value['identity'].get('qa_preview')!=drivers:raise ValueError('exact current frozen QA preview drivers required')
    report=value.get('report')
    if drivers and not isinstance(report,dict):raise ValueError('complete frozen QA preview report required')
    if drivers and isinstance(report.get('qa_preview'),dict) and report['qa_preview'].get('status')=='passed':
        from .browser import load_contract
        expected=[check['id'] for check in load_contract(store.tree(snapshot)/project.tests_dir)['checks']]
        if value['report']['qa_preview'].get('checks')!=expected:
            raise ValueError('frozen QA preview must execute the complete contract')


def review_decision(value, manifest, tree):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('ambiguous duplicate review field')
            result[key] = item
        return result

    if isinstance(value, str):
        if len(value) > 24000:
            raise ValueError('review decision exceeds bound')
        value = json.loads(value, object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'decision', 'reason', 'findings'}
            or value['decision'] not in ('approve', 'changes')
            or not isinstance(value['reason'], str) or not 1 <= len(value['reason'].strip()) <= 2000
            or not isinstance(value['findings'], list) or len(value['findings']) > 8):
        raise ValueError('approve or concrete change request required')
    if (value['decision']=='approve') != (not value['findings']):raise ValueError(REVIEW_FINDINGS_CONTRACT)
    for finding in value['findings']:
        if (not isinstance(finding, dict) or set(finding) != {'path', 'line', 'detail'}
                or finding['path'] not in manifest or type(finding['line']) is not int
                or not 1 <= finding['line'] <= len((tree / finding['path']).read_text().splitlines())
                or not isinstance(finding['detail'], str) or not 1 <= len(finding['detail'].strip()) <= 2000):
            raise ValueError('snapshot-bound finding required')
    return value


class Quality:
    def __init__(self, project, store, runner, board):
        self.project, self.store, self.runner, self.board = project, store, runner, board
        self.observed_jobs=set()
        self.control_refusal=None
        self.suite_refusal=None

    def check(self, run, kind, *, reviewing=False):
        self.board.ensure(run)
        if run.kind != kind or run.reviewing is not reviewing:
            raise ValueError('operation outside current native phase')
        if reviewing and run.actor == run.author:
            raise ValueError('independent reviewer required')

    def tests(self, snapshot):
        prefix = self.project.tests_dir + '/'
        return {p: value for p, value in self.store.manifest(snapshot).items() if p.startswith(prefix)}

    def correction_diff(self,before,after,paths):
        """V1 exception: reviewed expected text only; no actions, code or tests removed."""
        from .browser import contract
        left,right=self.store.manifest(before),self.store.manifest(after)
        if (not isinstance(paths,list) or not paths or len(paths)>20 or len(set(paths))!=len(paths)
                or any(p not in left or p not in right or not p.startswith(self.project.tests_dir+'/')
                    or not (p.rsplit('/',1)[-1]=='qa.json' or p.rsplit('/',1)[-1].startswith('qa.') and p.endswith('.json')) for p in paths)):
            raise ValueError('explicit existing QA contract paths required')
        changed={p for p in set(left)|set(right) if left.get(p)!=right.get(p)}
        if not changed or not changed<=set(paths):raise ValueError('correction may change only approved QA expectations')
        for p in changed:
            old=json.loads((self.store.tree(before)/p).read_bytes());new=json.loads((self.store.tree(after)/p).read_bytes())
            contract(old);contract(new)
            strip=lambda d:[{k:v for k,v in c.items() if k!='text'} for c in d['checks']]
            if strip(old)!=strip(new):raise ValueError('QA correction cannot remove or change IDs, actions, paths or selectors')

    def test_evidence(self,key):
        value=self.store.receipt(key)
        if value['kind'] not in ('red','regression_red','test_revision'):raise ValueError('actual Red or explicitly reviewed test revision required')
        return value

    def failures(self,report):
        """Stable assertion identities; never accept an arbitrary failing exit."""
        failures=report['failures'];prefix=self.project.tests_dir+'/'
        if (not failures or len({f['case'] for f in failures})!=len(failures)
                or any(f.get('assertion') is not True or not any(
                    frame['file'].startswith(prefix) and frame['function'].startswith('test')
                    for frame in f.get('frames',[])) for f in failures)):
            raise ValueError('known regression requires real existing-test assertion failures')
        return sorted((dict(case=f['case'],frames=f['frames'],detail=f.get('detail')) for f in failures),key=lambda f:f['case'])

    def known_regression(self,record):
        """Recheck immutable evidence without granting a current worker claim."""
        data=record['payload'];scope=record['binding']
        if (record['kind']!='regression_red' or data.get('control_contract')!=CONTROL_CONTRACT
                or data['project']!=self.project.fingerprint() or scope['kind']!='tests' or scope['reviewing']
                or not re.fullmatch('[a-f0-9]{40}',str(data['base_commit']))
                or data['baseline']!=data['snapshot'] or data['new_cases']):
            raise ValueError('exact controller-bound regression base required')
        facts=[]
        for field,phase in (('baseline_job','baseline'),('red_job','red')):
            job=self.store.receipt(data[field],kind='suite_job');value=job['payload'];identity=value['identity']
            if (job['binding']!=scope or identity['binding']!=scope or identity['phase']!=phase
                    or identity['snapshot']!=data['baseline'] or identity['project']!=self.project.fingerprint()
                    or identity['image']!=self.project.validation_image
                    or value['sandbox']!=dict(network='none',snapshot='readonly',user='65534:65534')):
                raise ValueError('exact isolated regression jobs required')
            preview_evidence(self.project,self.store,value,data['baseline'],phase)
            report=suite_report(value);facts.append((sorted(report['cases']),self.failures(report)))
        if facts[0]!=facts[1] or facts[0][0]!=data['cases']:
            raise ValueError('regression baseline and Red must reproduce the exact existing failures and inventory')
        return facts[0]

    def protect(self, before, after, *, exact_tests=False,allow_revision=False):
        left, right = self.store.manifest(before), self.store.manifest(after)
        # New test files are normal feature work. Only changes/removals of
        # pre-existing protected tests need the independently frozen exception.
        old_tests,new_tests=self.tests(before),self.tests(after)
        if allow_revision and any(new_tests.get(path)!=value for path,value in old_tests.items()):
            for path in (self.store.root/'receipts').glob('*.json'):
                record=self.store.receipt(path.stem)
                if record['kind']!='tests_frozen' or not record['payload'].get('revision'):continue
                data=record['payload']
                if data['baseline']==before and data['tests']==self.tests(after):
                    self.frozen_plan(record)
                    authority=self.store.receipt(self.store.receipt(data['revision'],kind='test_revision')['payload']['authority'],kind='plan_review')
                    proposal=self.store.receipt(authority['payload']['plan'],kind='work_plan')['payload']['document']
                    # CI may contain later product edits, but no other test edit.
                    protected_unchanged(left,right,prefixes=PROTECTED)
                    permitted=set(proposal['test_paths'])
                    if any(p not in permitted and left.get(p)!=right.get(p) for p in set(self.tests(before))|set(self.tests(after))):
                        raise ValueError('CI changed an unapproved test')
                    return
            raise ValueError('protected baseline changed: test correction lacks an exact independent freeze')
        protected_unchanged(left, right, prefixes=(*PROTECTED, self.project.tests_dir+'/'))
        protected_unchanged(right, left, prefixes=PROTECTED)
        if exact_tests and self.tests(before) != self.tests(after):
            raise ValueError('frozen test inventory changed')

    def observe(self, run, snapshot, phase):
        self.board.ensure(run)
        key = self.runner.run(run, snapshot, phase)
        receipt = self.store.receipt(key, kind='suite_job')
        value = receipt['payload']; identity = value['identity']; report = value['report']
        if (receipt['binding'] != run.binding() or identity['binding'] != run.binding()
                or identity['snapshot'] != snapshot or identity['phase'] != phase
                or identity['project'] != self.project.fingerprint()
                or identity['image'] != self.project.validation_image
                or value['sandbox'] != dict(network='none', snapshot='readonly', user='65534:65534')):
            raise ValueError('complete real suite without errors or skips required')
        preview_evidence(self.project,self.store,value,snapshot,phase)
        # Negative facts must remain visible to a diagnostician. Delivery phases
        # retain the strict default, including Red: errors/skips never qualify.
        try:report=suite_report(value,diagnostic=run.kind=='diagnostic')
        except ValueError as error:
            # Preserve complete negative facts from the existing job, never a
            # new approval. Invalid/partial reports still fail without credit.
            try:facts=suite_report(value,diagnostic=True)
            except ValueError:raise error
            self.suite_refusal=key
            details={field:dict(count=len(facts[field]),cases=facts[field][:8])
                     for field in ('errors','skips','expected_failures','unexpected_successes') if facts[field]}
            if facts.get('qa_preview',{}).get('status')=='failed':details['qa_preview']=facts['qa_preview']
            raise ValueError(phase+' suite rejected; job '+key+': '+json.dumps(details)+
                '. Fix the reported cases; this job does not qualify delivery or controls.') from None
        self.board.ensure(run)
        self.store.tree(snapshot)
        self.observed_jobs.add(key)
        return key, report

    def record(self, run, kind, payload):
        self.board.ensure(run)
        receipt=self.store.record(kind, run.binding(),
            {**payload, 'project': self.project.fingerprint(), 'qualification': self.project.qualification})
        jobs={payload[field] for field in ('job','baseline_job','red_job','validation_job') if isinstance(payload.get(field),str)}
        jobs.update(payload.get('jobs',[]));jobs&=self.observed_jobs
        if jobs:
            path=self.store.root/'progress'/(run.task+'-'+str(run.number)+'.json')
            try:
                with Journal(self.store.root/'effects').lock(['validation-progress',run.binding()]):
                    previous=json.loads(path.read_bytes()) if path.exists() else {}
                    seen=set(previous.get('jobs',[]))
                    if jobs-seen:write_json(path,dict(binding=run.binding(),receipt=receipt,jobs=sorted(jobs|seen),at=time.time()))
            except OSError:pass  # Optional monitor projection is not a quality gate; the receipt is already durable.
        return receipt

    def handoff(self, run, summary, evidence):
        """Derive conflicts from trusted receipts before assigning native review.

        No reviewer identity or exemption is accepted from worker prose. An
        exhausted approved pool remains an explicit technical impediment.
        """
        if run.kind not in ('tests', 'implementation'):
            raise ValueError('TDD handoff phase required')
        self.check(run, run.kind)
        required = {'red'} if run.kind == 'tests' else {'green', 'controls'}
        if not isinstance(evidence, dict) or set(evidence) != required:
            raise ValueError('exact TDD handoff evidence required')
        records = {key:(self.test_evidence(value) if key=='red' else self.store.receipt(value,kind=key))
                   for key,value in evidence.items()}
        if any(record['binding'] != run.binding()
               or record['payload']['project'] != self.project.fingerprint() for record in records.values()):
            raise ValueError('handoff must belong to the current execution')
        exclude = ()
        if run.kind == 'implementation':
            if records['controls']['payload']['green'] != evidence['green']:
                raise ValueError('controls for the exact Green required')
            frozen = self.freeze(run, records['green']['payload']['freeze'])
            exclude = (frozen['test_author'],)
        self.board.review(run, summary, evidence, exclude=exclude)

    def red(self, run, baseline, candidate):
        self.check(run, 'tests')
        from .repairs import repair_authority
        authority=repair_authority(self.project,self.store,self.board,run)
        if authority and authority['proposal']['classification']=='test_contract':
            self.correction_diff(baseline,candidate,authority['proposal']['test_paths'])
            if baseline!=authority['context']['snapshot']:raise ValueError('test correction base changed')
            self.browser_tests(run,candidate)
            base_job,base=self.observe(run,baseline,'baseline')
            job,report=self.observe(run,candidate,'green')
            prior=self.frozen_plan(self.store.receipt(authority['context']['tests'],kind='tests_frozen'))
            if base['failures'] or report['failures'] or set(report['cases'])!=set(prior['cases']):
                raise ValueError('test correction must preserve and pass the complete existing suite')
            historical=self.test_evidence(prior['red'])
            return self.record(run,'test_revision',dict(control_contract=CONTROL_CONTRACT,authority=authority['review'],
                historical_tests=authority['context']['tests'],historical_red=prior['red'],baseline=baseline,snapshot=candidate,
                baseline_job=base_job,validation_job=job,red_job=historical['payload']['red_job'],
                cases=report['cases'],new_cases=prior['new_cases'],control_cases=prior['control_cases']))
        self.protect(baseline, candidate)
        left, right = self.store.manifest(baseline), self.store.manifest(candidate)
        prefix = self.project.tests_dir+'/'
        if any(not p.startswith(prefix) and left.get(p) != right.get(p) for p in set(left) | set(right)):
            raise ValueError('tests-only phase changed product')
        self.browser_tests(run,candidate)
        base_job, base = self.observe(run, baseline, 'baseline')
        if base['failures']:
            if candidate!=baseline:raise ValueError('regression baseline failed: submit unchanged existing tests, never duplicate or alter them')
            commit=self.board.input(run,'base_commit')
            if not re.fullmatch('[a-f0-9]{40}',commit):raise ValueError('controller baseline commit required for known regression')
            self.failures(base)
            red_job,report=self.observe(run,baseline,'red')
            if sorted(base['cases'])!=sorted(report['cases']) or self.failures(base)!=self.failures(report):
                raise ValueError('regression failures or discovery changed during confirmation')
            return self.record(run,'regression_red',dict(control_contract=CONTROL_CONTRACT,baseline=baseline,snapshot=baseline,
                base_commit=commit,baseline_job=base_job,red_job=red_job,cases=sorted(base['cases']),new_cases=[]))
        red_job, report = self.observe(run, candidate, 'red')
        old, all_cases = set(base['cases']), set(report['cases'])
        new, failing = all_cases-old, {f['case'] for f in report['failures']}
        if not old <= all_cases or not failing or not failing <= new:
            raise ValueError('Red must fail new behavior and preserve baseline membership')
        for failure in report['failures']:
            if not failure['assertion'] or not any(f['file'].startswith(prefix) and
                    f['function'].startswith('test') for f in failure['frames']):
                raise ValueError('Red requires an assertion in a new test body')
        return self.record(run, 'red', dict(control_contract=CONTROL_CONTRACT,baseline=baseline, snapshot=candidate,
            baseline_job=base_job, red_job=red_job, cases=sorted(all_cases), new_cases=sorted(new)))

    def control_plan(self,red,risks):
        data=red['payload']
        if red['kind']=='test_revision':
            from .repairs import validate_revision
            validate_revision(self.project,self.store,self,red)
            required=set(data['control_cases']);extra=set()
            if not isinstance(risks,list) or len(risks)>32:raise ValueError('bounded control risks required')
            for risk in risks:
                if (not isinstance(risk,dict) or set(risk)!={'case','reason'} or risk['case'] not in data['cases']
                        or risk['case'] in required|extra or not isinstance(risk['reason'],str) or not 1<=len(risk['reason'].strip())<=2000):
                    raise ValueError('distinct preserved control cases required')
                extra.add(risk['case'])
            return sorted(required|extra)
        if red['kind']=='regression_red':self.known_regression(red)
        if data.get('control_contract')!=CONTROL_CONTRACT:
            raise ValueError('new Red evidence required for the approved behavior-control contract; no legacy conversion')
        job=self.store.receipt(data['red_job'],kind='suite_job');value=job['payload'];identity=value['identity']
        preview_evidence(self.project,self.store,value,data['snapshot'],'red')
        if (job['binding']!=red['binding'] or identity['binding']!=red['binding']
                or identity['snapshot']!=data['snapshot'] or identity['phase']!='red'
                or identity['project']!=self.project.fingerprint() or identity['image']!=self.project.validation_image):
            raise ValueError('mutation targets require the exact validated Red job')
        report=suite_report(value);required=set()
        for failure in report['failures']:
            if not failure['assertion'] or not any(f['file'].startswith(self.project.tests_dir+'/') and
                    f['function'].startswith('test') for f in failure['frames']):
                raise ValueError('mutation targets require actual Red assertions in protected test bodies')
            required.add(failure['case'])
        eligible=data['cases'] if red['kind']=='regression_red' else data['new_cases']
        if (not required or not required<=set(eligible) or set(report['cases'])!=set(data['cases'])
                or not isinstance(risks,list) or len(risks)>32):
            raise ValueError('validated Red cases and bounded independently reviewed risks required')
        extra=set()
        for risk in risks:
            if (not isinstance(risk,dict) or set(risk)!={'case','reason'} or not isinstance(risk['case'],str)
                    or risk['case'] not in report['cases'] or risk['case'] in required|extra
                    or not isinstance(risk['reason'],str) or not 1<=len(risk['reason'].strip())<=2000):
                raise ValueError('control_risks requires distinct passing suite cases and concrete reasons; Red targets are automatic')
            extra.add(risk['case'])
        return sorted(required|extra)

    def browser_tests(self,run,snapshot):
        if not self.project.delivery_roles:return
        from .browser import load_contract
        checks=load_contract(self.store.tree(snapshot)/self.project.tests_dir)['checks']
        if not set(self.board.criteria(run))<={item['id'] for item in checks}:
            raise ValueError('browser scenarios must cover every current package acceptance criterion before Red')

    def tests_review(self, run, red_id, decision, *, control_risks=None):
        self.check(run, 'tests', reviewing=True)
        if self.board.input(run, 'red', review_handoff=True) != red_id:
            raise ValueError('obsolete test review input')
        red = self.test_evidence(red_id)
        data = red['payload']
        if (red['binding']['task'] != run.task or red['binding']['contract'] != run.contract
                or red['binding']['actor'] != run.author or data['project'] != self.project.fingerprint()):
            raise ValueError('review must match exact test authorship and contract')
        snapshot = data['snapshot']
        verdict = review_decision(decision, self.store.manifest(snapshot), self.store.tree(snapshot))
        risks=[] if control_risks is None else control_risks
        if verdict['decision']=='approve':
            self.browser_tests(run,snapshot);targets=self.control_plan(red,risks)
        elif risks!=[]:raise ValueError('only approval may freeze additional control risks')
        review = self.record(run, 'test_review', dict(red=red_id, snapshot=snapshot, verdict=verdict,control_risks=risks))
        if verdict['decision'] != 'approve':
            return review
        return self.record(run, 'tests_frozen', dict(control_contract=CONTROL_CONTRACT,control_cases=targets,
            red=red_id, review=review, snapshot=snapshot,
            baseline=data['baseline'], tests=self.tests(snapshot), cases=data['cases'],
            new_cases=data['new_cases'], test_author=red['binding']['actor'],
            **({'revision':red_id} if red['kind']=='test_revision' else {})))

    def freeze(self, run, freeze_id):
        if self.board.input(run, 'tests') != freeze_id:
            raise ValueError('implementation requires its exact frozen-test input')
        receipt = self.store.receipt(freeze_id, kind='tests_frozen')
        data = receipt['payload']
        if data['project'] != self.project.fingerprint() or receipt['binding']['release'] != run.release:
            raise ValueError('frozen tests belong to another project or release')
        return self.frozen_plan(receipt)

    def frozen_plan(self,receipt):
        """Read current immutable quality semantics, without granting run authority."""
        data=receipt['payload']
        if data.get('control_contract')!=CONTROL_CONTRACT or data.get('project')!=self.project.fingerprint():
            raise ValueError('frozen tests use a historical control contract; new independent review required')
        red=self.test_evidence(data['red']);review=self.store.receipt(data['review'],kind='test_review')
        if red['kind']=='regression_red':
            origin,scope=red['binding'],receipt['binding']
            if (scope['kind']!='tests' or scope['reviewing'] is not True or scope['task']!=origin['task']
                    or scope['release']!=origin['release'] or scope['contract']!=origin['contract']
                    or scope['author']!=origin['actor'] or scope['actor'] not in self.project.reviewers_for(origin['actor'])
                    or scope['number']<=origin['number'] or data['tests']!=self.tests(data['snapshot'])
                    or data['baseline']!=red['payload']['baseline']):
                raise ValueError('independent exact regression freeze required')
        if (review['binding']!=receipt['binding'] or review['payload']['project']!=self.project.fingerprint()
                or review['payload']['red']!=data['red'] or review['payload']['snapshot']!=data['snapshot']
                or review['payload']['verdict']['decision']!='approve' or red['payload']['snapshot']!=data['snapshot']
                or red['binding']['actor']!=data['test_author'] or receipt['binding']['actor']==data['test_author']
                or data['cases']!=red['payload']['cases'] or data['new_cases']!=red['payload']['new_cases']
                or data['control_cases']!=self.control_plan(red,review['payload']['control_risks'])):
            raise ValueError('exact independently frozen behavior-control targets required')
        self.store.tree(data['snapshot'])
        return data

    def regression_ci(self,commit,baseline,snapshot,report):
        """Only an independently reviewed fix may reuse known failing base facts."""
        for path in sorted((self.store.root/'receipts').glob('*.json')):
            review=self.store.receipt(path.stem)
            if review['kind']!='delivery_review':continue
            scope,data=review['binding'],review['payload']
            if data['project']!=self.project.fingerprint() or data['snapshot']!=snapshot:continue
            green=self.store.receipt(data['green'],kind='green');freeze=self.store.receipt(green['payload']['freeze'],kind='tests_frozen')
            red=self.test_evidence(freeze['payload']['red'])
            if red['kind']!='regression_red' or red['payload']['base_commit']!=commit or red['payload']['baseline']!=baseline:continue
            frozen=self.frozen_plan(freeze);author=green['binding']
            if (scope['kind']!='implementation' or scope['reviewing'] is not True or scope['author']!=author['actor']
                    or scope['actor'] not in self.project.reviewers_for(author['actor']) or scope['actor']==frozen['test_author']
                    or scope['task']!=author['task'] or scope['contract']!=author['contract'] or scope['release']!=author['release']
                    or scope['number']<=author['number'] or author['release']!=freeze['binding']['release']
                    or data['verdict']['decision']!='approve' or data['verdict']['findings']
                    or green['payload']['snapshot']!=snapshot or self.tests(snapshot)!=frozen['tests']):
                raise ValueError('exact independently reviewed product-only regression fix required')
            if (sorted(report['cases']),self.failures(report))!=self.known_regression(red):
                raise ValueError('CI baseline differs from the exact reviewed regression failures or inventory')
            self.protect(baseline,snapshot,exact_tests=True)
            return path.stem
        raise EffectBlocked('CI failing base lacks an exact independently reviewed regression fix')

    def green(self, run, freeze_id, snapshot):
        self.check(run, 'implementation')
        frozen = self.freeze(run, freeze_id)
        self.protect(frozen['snapshot'], snapshot, exact_tests=True)
        job, report = self.observe(run, snapshot, 'green')
        if report['failures'] or set(report['cases']) != set(frozen['cases']):
            raise ValueError('Green requires complete frozen membership passing')
        return self.record(run, 'green', dict(freeze=freeze_id, snapshot=snapshot, job=job, cases=report['cases']))

    def controls(self, run, green_id, mutants):
        self.check(run, 'implementation')
        green = self.store.receipt(green_id, kind='green')
        if green['binding'] != run.binding() or not 1 <= len(mutants) <= 8:
            raise ValueError('controls must belong to the current Green execution')
        data = green['payload']; frozen = self.freeze(run, data['freeze'])
        if preview_drivers(self.project,'green'):
            value=self.store.receipt(data['job'],kind='suite_job')['payload']
            preview_evidence(self.project,self.store,value,data['snapshot'],'green');suite_report(value)
        coverage, jobs = set(), []
        for mutant in mutants:
            if mutant == data['snapshot']:
                raise ValueError('control must change product behavior')
            self.protect(data['snapshot'], mutant, exact_tests=True)
            job, report = self.observe(run, mutant, 'control')
            if set(report['cases']) != set(frozen['cases']) or not report['failures']:
                raise ValueError('negative control must fail the complete frozen suite')
            for failure in report['failures']:
                if failure['assertion'] and any(f['file'].startswith(self.project.tests_dir+'/') and
                        f['function'].startswith('test') for f in failure['frames']):
                    coverage.add(failure['case'])
            jobs.append(job)
        missing=sorted(set(frozen['control_cases'])-coverage)
        if missing:
            feedback=dict(missing=missing[:32],missing_count=len(missing),covered=sorted(coverage)[:32],
                covered_count=len(coverage),required_count=len(frozen['control_cases']))
            self.control_refusal=self.record(run,'control_refusal',dict(green=green_id,freeze=data['freeze'],
                snapshot=data['snapshot'],jobs=jobs,missing=missing,coverage=sorted(coverage),feedback=feedback,delivery_approval=False))
            raise ValueError('negative controls did not witness all independently frozen behavior targets: '+json.dumps({**feedback,'refusal':self.control_refusal})+
                '. Correct product mutations for the missing cases; preserve the full suite and frozen tests.')
        self.control_refusal=None
        return self.record(run, 'controls', dict(control_contract=CONTROL_CONTRACT,green=green_id, jobs=jobs, coverage=sorted(coverage)))

    def delivery_review(self, run, green_id, controls_id, decision):
        self.check(run, 'implementation', reviewing=True)
        if (self.board.input(run, 'green', review_handoff=True) != green_id
                or self.board.input(run, 'controls', review_handoff=True) != controls_id):
            raise ValueError('obsolete delivery review input')
        green = self.store.receipt(green_id, kind='green')
        controls = self.store.receipt(controls_id, kind='controls')
        data = green['payload']; frozen = self.freeze(run, data['freeze'])
        if (green['binding']['task'] != run.task or green['binding']['contract'] != run.contract
                or green['binding']['actor'] != run.author or run.actor == frozen['test_author']
                or controls['payload']['green'] != green_id or controls['binding'] != green['binding']):
            raise ValueError('independent review of exact current delivery required')
        job, report = self.observe(run, data['snapshot'], 'delivery')
        if report['failures'] or set(report['cases']) != set(frozen['cases']):
            raise ValueError('review validation must pass on the same complete suite')
        decision = review_decision(decision, self.store.manifest(data['snapshot']), self.store.tree(data['snapshot']))
        return self.record(run, 'delivery_review', dict(green=green_id, controls=controls_id,
            snapshot=data['snapshot'], validation_job=job, verdict=decision,
            merge_authorized=False, delivery_approval=False))

    def review_recurrence(self,run,verdict):
        """Escalate review churn, never limit handoffs or infer the root cause."""
        if verdict['decision']!='changes':return None
        self.check(run,run.kind,reviewing=True)
        reader=getattr(self.board,'review_feedback',None)
        history=reader(run,self.store) if reader else []
        if not isinstance(history,list):raise ValueError('validated native review history required')
        if len(history)<2:return None
        common={f['path'] for f in verdict['findings']};references=[];numbers=[]
        for item in history[-2:]:
            record=self.store.receipt(item['receipt'],kind='test_review' if run.kind=='tests' else 'delivery_review')
            scope,data=record['binding'],record['payload']
            if (scope['task']!=run.task or scope['contract']!=run.contract or scope['release']!=run.release
                    or scope['kind']!=run.kind or scope['reviewing'] is not True or scope['author']!=run.author
                    or scope['actor'] not in self.project.reviewers_for(run.author) or scope['number']>=run.number
                    or data['project']!=self.project.fingerprint() or data['verdict']['decision']!='changes'
                    or data['verdict']!=item['verdict'] or data['snapshot']!=item['snapshot']):
                raise ValueError('repeated findings require exact independent native review evidence')
            common&={f['path'] for f in data['verdict']['findings']}
            references.append(item['receipt']);numbers.append(scope['number'])
        if numbers!=sorted(set(numbers)):raise ValueError('distinct chronological reviews required')
        return dict(reviews=references,paths=sorted(common)) if common else None


def product_mutations(quality,snapshot,proposals):
    """Disposable experiments; never modify the author or protected tests."""
    store=quality.store
    if not isinstance(proposals,list) or not 1<=len(proposals)<=8:
        raise ValueError('one to eight bounded product mutations required')
    manifest=store.manifest(snapshot);result=[];total=0
    for proposal in proposals:
        if not isinstance(proposal,dict) or not 1<=len(proposal)<=16:
            raise ValueError('bounded product-file replacements required')
        for path,content in proposal.items():
            if path not in manifest or not isinstance(content,str) or len(content)>131072:
                raise ValueError('mutation may replace only a bounded existing product file')
            total+=len(content)
            if total>1024*1024:raise ValueError('mutation proposals exceed total bound')
        with tempfile.TemporaryDirectory(prefix='.delivery-mutant-',dir=store.root.parent) as folder:
            work=Path(folder);store.checkout(snapshot,work)
            for path,content in proposal.items():(work/path).write_text(content)
            mutant=store.capture(work)
        quality.protect(snapshot,mutant,exact_tests=True)
        if mutant==snapshot or mutant in result:raise ValueError('distinct behavior-changing controls required')
        result.append(mutant)
    return result


class DeliveryTools:
    """Fixed model-facing operations. IDs, phase and authority are server-owned."""
    def __init__(self,sandbox,quality):
        if (quality.store is not sandbox.store or quality.board is not sandbox.board
                or quality.project.fingerprint()!=sandbox.project.fingerprint()
                or sandbox.run.kind not in ('tests','implementation')):
            raise ValueError('same controller and current TDD activity required')
        self.sandbox,self.quality,self.run=sandbox,quality,sandbox.run
        self.store,self.board=quality.store,quality.board
        self.submission=None;self.verdict=None;self.escalating=None;self.reviewed_risks=None;self.recurrence=None

    def wait(self,call,*,jobs=1):
        # These are actual local validation jobs, not model polling or CI waits.
        # Runner owns the per-job deadline/retirement; this is a composite backstop.
        deadline=time.monotonic()+jobs*(self.quality.project.timeout_seconds+15)
        while True:
            try:return call()
            except Pending:
                if time.monotonic()>=deadline:raise EffectBlocked('local gate observation deadline exhausted')
                time.sleep(0.1)

    def mutants(self,snapshot,proposals):
        return product_mutations(self.quality,snapshot,proposals)

    def submit(self,args):
        q,run=self.quality,self.run
        q.check(run,run.kind)
        required=set() if run.kind=='tests' else {'mutations'}
        if not isinstance(args,dict) or set(args)!=required:
            raise ValueError('submit accepts only the phase-specific evidence proposal')
        if self.submission is None:
            snapshot=self.store.capture(self.sandbox.workspace)
            exclude=()
            if run.kind=='tests':
                baseline=self.board.input(run,'baseline')
                evidence={'red':self.wait(lambda:q.red(run,baseline,snapshot),jobs=2)}
            else:
                frozen_id=self.board.input(run,'tests')
                green=self.wait(lambda:q.green(run,frozen_id,snapshot))
                mutants=self.mutants(snapshot,args['mutations'])
                controls=self.wait(lambda:q.controls(run,green,mutants),jobs=len(mutants))
                exclude=(q.freeze(run,frozen_id)['test_author'],)
                evidence={'green':green,'controls':controls}
            q.project.reviewer(run.author,exclude=exclude)
            self.submission=evidence
        self.sandbox.close()
        q.handoff(run,'Controller-validated immutable '+run.kind+' submission',self.submission)
        return dict(status='review_requested',task=run.task,evidence=self.submission,delivery_approval=False)

    def review(self,decision):
        q,run=self.quality,self.run
        q.check(run,run.kind,reviewing=True)
        if not isinstance(decision,dict):raise ValueError('structured independent review required')
        risks=decision.get('control_risks',[])
        if 'control_risks' in decision and run.kind!='tests':raise ValueError('control_risks belongs only to independent test review')
        decision={key:value for key,value in decision.items() if key!='control_risks'}
        escalate=isinstance(decision,dict) and decision.get('decision')=='escalate'
        effective={**decision,'decision':'changes'} if escalate else decision
        if self.verdict is None:
            self.escalating=escalate
            if run.kind=='tests':
                red=self.board.input(run,'red',review_handoff=True)
                receipt=q.tests_review(run,red,effective,control_risks=risks)
                result=self.store.receipt(receipt)
                changes=result['kind']=='test_review'
                if changes:verdict=result['payload']['verdict']
                else:verdict=self.store.receipt(result['payload']['review'])['payload']['verdict']
                evidence={'review' if changes else 'tests':receipt}
            else:
                green=self.board.input(run,'green',review_handoff=True)
                controls=self.board.input(run,'controls',review_handoff=True)
                receipt=self.wait(lambda:q.delivery_review(run,green,controls,effective))
                verdict=self.store.receipt(receipt)['payload']['verdict']
                changes=verdict['decision']=='changes'
                evidence={'review' if changes else 'delivery':receipt}
            self.verdict=(verdict,evidence,changes)
            self.recurrence=q.review_recurrence(run,verdict) if changes and not escalate else None
            self.reviewed_risks=json.loads(json.dumps(risks))
        verdict,evidence,changes=self.verdict
        if effective!=verdict or escalate!=self.escalating or risks!=self.reviewed_risks:
            raise ValueError('pending review decision cannot change during retirement')
        self.sandbox.close()
        if escalate or self.recurrence:
            review=self.store.receipt(evidence['review'])
            receipt=q.record(run,'review_escalation',dict(review=evidence['review'],snapshot=review['payload']['snapshot'],
                **({'recurrence':self.recurrence} if self.recurrence else {})))
            self.board.escalate_review(run,receipt)
            return dict(status='technical_diagnosis_requested',task=run.task,escalation=receipt,delivery_approval=False)
        self.board.finish_review(run,verdict['reason'],evidence,changes=changes)
        return dict(status='changes_requested' if changes else 'completed',task=run.task,
                    evidence=evidence,delivery_approval=False)

    def evidence(self):
        """Trusted initial review context; no arbitrary receipt/path read API."""
        q,run=self.quality,self.run;q.check(run,run.kind,reviewing=True)
        def payload(key,kind):return self.store.receipt(key,kind=kind)['payload']
        def report(key):return payload(key,'suite_job')['report']
        context=dict(phase=run.kind,mutations=[],control_review_contract=CONTROL_REVIEW_CONTRACT)
        if run.kind=='tests':
            evidence=q.test_evidence(self.board.input(run,'red',review_handoff=True));red=evidence['payload']
        else:
            green=payload(self.board.input(run,'green',review_handoff=True),'green')
            frozen=payload(green['freeze'],'tests_frozen');evidence=q.test_evidence(frozen['red']);red=evidence['payload']
            context['frozen_control_cases']=frozen['control_cases']
            controls=payload(self.board.input(run,'controls',review_handoff=True),'controls')
            context['green']=report(green['job'])
            before=self.store.manifest(green['snapshot'])
            for job in controls['jobs']:
                data=payload(job,'suite_job');snapshot=data['identity']['snapshot']
                after=self.store.manifest(snapshot);changes=[]
                for path in before:
                    if before[path]==after.get(path):continue
                    change=dict(path=path,before=before[path],after=after.get(path),diff=None,truncated=True)
                    if max(before[path]['bytes'],after.get(path,{}).get('bytes',0))<=131072 and path in after:
                        left=(self.store.tree(green['snapshot'])/path).read_text(errors='replace').splitlines(True)
                        right=(self.store.tree(snapshot)/path).read_text(errors='replace').splitlines(True)
                        lines=list(islice(difflib.unified_diff(left,right,fromfile=path,tofile=path),301))
                        change.update(diff=''.join(lines[:300]),truncated=len(lines)>300)
                    changes.append(change)
                context['mutations'].append(dict(report=data['report'],changes=changes))
        context.update(baseline=report(red['baseline_job']),red=report(red['red_job']))
        if evidence['kind']=='test_revision':
            context.update(test_revision=red,historical_red_only=True,
                correction_validation=report(red['validation_job']),
                instructions='Review this new expected-text correction against the approved brief and repair authority. Historical Red remains historical; no new failing test is claimed. Preserve every unit test, action and control target.')
        elif evidence['kind']=='regression_red':
            context.update(regression_red=red,instructions='Known regression at the controller base SHA: independently confirm the existing expectation and every exact assertion failure. No new test is claimed. Preserve all tests and require a product-only fix, full Green and negative controls before independent delivery approval.')
        context['mandatory_red_targets']=sorted({failure['case'] for failure in context['red']['failures']})
        context['passing_cases']=sorted(set(context['red']['cases'])-set(context['mandatory_red_targets']))
        return context
