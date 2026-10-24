"""Small TDD gates over controller-owned jobs and current native run identities.

No worker-supplied pass flags or receipt imports. Store and Runner live only in
the controller; model output is limited to a review decision with findings.
"""
import json
from .artifacts import protected_unchanged

PROTECTED = ('.github/', 'pyproject.toml', 'pytest.ini', 'setup.cfg', 'tox.ini',
             'requirements.txt', 'package.json', 'package-lock.json')


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
            or not isinstance(value['findings'], list) or len(value['findings']) > 8
            or (value['decision'] == 'approve') != (len(value['findings']) == 0)):
        raise ValueError('approve or concrete change request required')
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

    def check(self, run, kind, *, reviewing=False):
        self.board.ensure(run)
        if run.kind != kind or run.reviewing is not reviewing:
            raise ValueError('operation outside current native phase')
        if reviewing and run.actor == run.author:
            raise ValueError('independent reviewer required')

    def tests(self, snapshot):
        prefix = self.project.tests_dir + '/'
        return {p: value for p, value in self.store.manifest(snapshot).items() if p.startswith(prefix)}

    def protect(self, before, after, *, exact_tests=False):
        left, right = self.store.manifest(before), self.store.manifest(after)
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
                or value['sandbox'] != dict(network='none', snapshot='readonly', user='65534:65534')
                or not isinstance(report, dict) or report.get('version') != 1
                or type(report.get('tests_run')) is not int or report['tests_run'] < 1
                or not isinstance(report.get('cases'), list)
                or report['tests_run'] != len(report['cases']) or len(set(report['cases'])) != len(report['cases'])
                or any(not isinstance(p, str) or not p for p in report['cases'])
                or any(not isinstance(report.get(field), list) for field in
                       ('failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes'))
                or any(report[field] for field in ('errors', 'skips', 'expected_failures', 'unexpected_successes'))):
            raise ValueError('complete real suite without errors or skips required')
        failed = {f['case'] for f in report['failures']}
        if not failed <= set(report['cases']) or value['exit_code'] != (1 if failed else 0):
            raise ValueError('suite exit and assertion facts disagree')
        self.board.ensure(run)
        self.store.tree(snapshot)
        return key, report

    def record(self, run, kind, payload):
        self.board.ensure(run)
        return self.store.record(kind, run.binding(),
            {**payload, 'project': self.project.fingerprint(), 'qualification': self.project.qualification})

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
        records = {key:self.store.receipt(value,kind=key) for key,value in evidence.items()}
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
        self.protect(baseline, candidate)
        left, right = self.store.manifest(baseline), self.store.manifest(candidate)
        prefix = self.project.tests_dir+'/'
        if any(not p.startswith(prefix) and left.get(p) != right.get(p) for p in set(left) | set(right)):
            raise ValueError('tests-only phase changed product')
        base_job, base = self.observe(run, baseline, 'baseline')
        if base['failures']:
            raise ValueError('baseline must pass before Red')
        red_job, report = self.observe(run, candidate, 'red')
        old, all_cases = set(base['cases']), set(report['cases'])
        new, failing = all_cases-old, {f['case'] for f in report['failures']}
        if not old <= all_cases or not failing or not failing <= new:
            raise ValueError('Red must fail new behavior and preserve baseline membership')
        for failure in report['failures']:
            if not failure['assertion'] or not any(f['file'].startswith(prefix) and
                    f['function'].startswith('test') for f in failure['frames']):
                raise ValueError('Red requires an assertion in a new test body')
        return self.record(run, 'red', dict(baseline=baseline, snapshot=candidate,
            baseline_job=base_job, red_job=red_job, cases=sorted(all_cases), new_cases=sorted(new)))

    def tests_review(self, run, red_id, decision):
        self.check(run, 'tests', reviewing=True)
        if self.board.input(run, 'red', review_handoff=True) != red_id:
            raise ValueError('obsolete test review input')
        red = self.store.receipt(red_id, kind='red')
        data = red['payload']
        if (red['binding']['task'] != run.task or red['binding']['contract'] != run.contract
                or red['binding']['actor'] != run.author or data['project'] != self.project.fingerprint()):
            raise ValueError('review must match exact test authorship and contract')
        snapshot = data['snapshot']
        verdict = review_decision(decision, self.store.manifest(snapshot), self.store.tree(snapshot))
        review = self.record(run, 'test_review', dict(red=red_id, snapshot=snapshot, verdict=verdict))
        if verdict['decision'] != 'approve':
            return review
        return self.record(run, 'tests_frozen', dict(red=red_id, review=review, snapshot=snapshot,
            baseline=data['baseline'], tests=self.tests(snapshot), cases=data['cases'],
            new_cases=data['new_cases'], test_author=red['binding']['actor']))

    def freeze(self, run, freeze_id):
        if self.board.input(run, 'tests') != freeze_id:
            raise ValueError('implementation requires its exact frozen-test input')
        receipt = self.store.receipt(freeze_id, kind='tests_frozen')
        data = receipt['payload']
        if data['project'] != self.project.fingerprint() or receipt['binding']['release'] != run.release:
            raise ValueError('frozen tests belong to another project or release')
        self.store.tree(data['snapshot'])
        return data

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
        if not set(frozen['new_cases']) <= coverage:
            raise ValueError('negative controls did not witness all new test behaviors')
        return self.record(run, 'controls', dict(green=green_id, jobs=jobs, coverage=sorted(coverage)))

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
