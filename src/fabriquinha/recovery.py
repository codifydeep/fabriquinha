"""Executable technical diagnostics as native Kanban cards, not another workflow DB."""
import json
from pathlib import Path
import tempfile
import time
import re
import subprocess
from .artifacts import digest,encoded
from .board import Run
from .effects import Journal, EffectBlocked, Pending,write_json
from .kanban_lane import native
from .quality import Quality, DeliveryTools, product_mutations, review_decision, suite_report,PROTECTED


def guidance_context(guidance):
    """Prompt projection only; full checked experiments remain immutable receipts.

    Test inventory names are already in the frozen workspace and suite receipt.
    Keep every failure/error detail and verdict; omit only repeated inventories.
    This view must never be used for validation or recovery authorization.
    """
    result=json.loads(json.dumps(guidance))
    for item in result:
        experiment=item.get('experiment',{});report=experiment.get('report')
        if not isinstance(report,dict) or not isinstance(experiment.get('job'),str):continue
        for section in (report,report.get('qa_preview')):
            if not isinstance(section,dict):continue
            cases=section.get('cases')
            if isinstance(cases,list) and all(isinstance(case,str) for case in cases):
                section['case_inventory']=dict(receipt=experiment['job'],count=len(cases))
                del section['cases']
    return result


def browser_refusal_context(store,project,binding,key):
    record=store.receipt(key,kind='browser_job');data=record['payload'];identity=data['identity'];report=data['report']
    if (binding.get('kind')!='integration' or binding.get('reviewing') is not True
            or binding.get('actor')==binding.get('author') or record['binding']!=binding or identity['binding']!=binding
            or identity['project']!=project.fingerprint() or identity['phase']!='browser'
            or identity['image']!=project.browser_image
            or not re.fullmatch('[a-f0-9]{40}',str(identity.get('commit')))
            or data['sandbox']!=dict(network=project.namespace+'-homologation_qa',snapshot='readonly',user='10000:10000')):
        raise ValueError('browser refusal must match the exact independent deployed QA execution')
    store.tree(identity['snapshot'])
    if not data['infrastructure_error']:
        if (data['exit_code']!=1 or not isinstance(report,dict) or type(report.get('version')) is not int or report.get('version')!=1
                or report.get('status')!='failed' or report.get('source_sha')!=identity['commit']
                or not isinstance(report.get('checks'),list) or len(report['checks'])>20
                or not all(isinstance(check,str) and 1<=len(check)<=1000 for check in report['checks'])
                or len(set(report['checks']))!=len(report['checks'])
                or not isinstance(report.get('errors'),list) or not 1<=len(report['errors'])<=100
                or not all(isinstance(error,str) and 1<=len(error)<=1000 for error in report['errors'])):
            raise ValueError('complete negative browser facts required; not a delivery approval')
    classification='infrastructure' if data['infrastructure_error'] else report.get('failure_kind','unclassified')
    return dict(receipt=key,snapshot=identity['snapshot'],commit=identity['commit'],report=report,
        infrastructure_error=data['infrastructure_error'],classification=classification,
        delivery_approval=False,requires_fresh_validation=True)


def submission_refusal_context(store,project,binding,key,current_snapshot):
    record=store.receipt(key,kind='submission_refusal');data=record['payload']
    if (record['binding']!=binding or data['project']!=project.fingerprint()
            or data['phase']!='tests' or data['operation']!='delivery_submit' or data['delivery_approval'] is not False):
        raise ValueError('submission refusal requires exact tests execution')
    store.tree(data['snapshot']);store.tree(data['baseline'])
    return dict(receipt=key,**data,current_workspace_matches=data['snapshot']==current_snapshot,
        semantics='Rejected candidate is preserved evidence, not approved tests. A passing current baseline does not diagnose this rejection. Inspect the rejected snapshot and error; preserve all gates.')


def suite_refusal_context(store,project,binding,key,current_snapshot):
    record=store.receipt(key,kind='suite_job');data=record['payload'];identity=data['identity']
    if record['binding']!=binding:
        from .control_submission import refusal_origin
        binding=refusal_origin(store,project,binding,record)
    if (record['binding']!=binding or identity['binding']!=binding or identity['project']!=project.fingerprint()
            or identity['image']!=project.validation_image or identity['phase']=='diagnostic'
            or data['sandbox']!=dict(network='none',snapshot='readonly',user='65534:65534')):
        raise ValueError('suite refusal must match the exact failed execution and fixed validator')
    store.tree(identity['snapshot'])
    if data.get('infrastructure_error'):
        return dict(receipt=key,phase=identity['phase'],snapshot=identity['snapshot'],report=None,
            infrastructure_error=data['infrastructure_error'],progress=data.get('progress',[]),
            progress_semantics='Sandbox diagnostic clues only; incomplete execution is never Red, Green or approval.',
            matches_current_snapshot=identity['snapshot']==current_snapshot,
            delivery_approval=False,requires_fresh_validation=True)
    report=suite_report(data,diagnostic=True)
    if not any(report[field] for field in ('errors','skips','expected_failures','unexpected_successes')) and report.get('qa_preview',{}).get('status')!='failed':
        raise ValueError('negative quality report required, never a passing-job approval')
    return dict(receipt=key,phase=identity['phase'],snapshot=identity['snapshot'],report=report,
        matches_current_snapshot=identity['snapshot']==current_snapshot,delivery_approval=False,requires_fresh_validation=True)


def control_refusal_context(store,project,binding,key,current_snapshot):
    record=store.receipt(key,kind='control_refusal');data=record['payload']
    green=store.receipt(data['green'],kind='green')
    if record['binding']!=binding:
        from .control_submission import refusal_origin
        binding=refusal_origin(store,project,binding,record)
    if (binding.get('kind')!='implementation' or binding.get('reviewing') is not False
            or record['binding']!=binding or green['binding']!=binding
            or data['project']!=project.fingerprint() or green['payload']['project']!=project.fingerprint()
            or data['snapshot']!=green['payload']['snapshot'] or data['freeze']!=green['payload']['freeze']
            or data.get('delivery_approval') is not False):
        raise ValueError('control refusal must match its exact failed execution, Green and frozen contract')
    store.tree(data['snapshot'])
    feedback=data['feedback'];missing=data.get('missing',feedback['missing']);coverage=data.get('coverage',feedback['covered'])
    return dict(receipt=key,snapshot=data['snapshot'],matches_current_snapshot=data['snapshot']==current_snapshot,
        feedback=feedback,missing=missing,coverage=coverage,
        complete=len(missing)==feedback['missing_count'] and len(coverage)==feedback['covered_count'],
        delivery_approval=False,requires_fresh_validation=True)


def source_package_context(body,binding):
    """Exact failed work scope; baseline inventory is not its unfinished work."""
    if not body.get('package'):return None
    if digest(body)!=binding['contract'] or body.get('release')!=binding['release']:
        raise ValueError('exact failed package contract required')
    return dict(package=body['package'],criteria=body.get('criteria',[]),
        acceptance=body.get('acceptance',''),release_plan=body.get('release_plan'),
        semantics='Diagnose this package only. Passing baseline tests are prior regressions, not evidence that new criteria exist or that old behavior needs a new Red.')


class Diagnostic:
    def __init__(self,sandbox,quality):
        self.sandbox,self.q,self.run=sandbox,quality,sandbox.run
        self.store,self.board=quality.store,quality.board
        self.board.ensure(self.run)
        record=self.store.receipt(self.board.input(self.run,'incident'),kind='incident')
        self.incident,self.original=record['payload'],record['binding']
        roles=quality.project.technical_roles
        if (self.run.kind!='diagnostic' or self.run.reviewing or not roles or self.run.actor not in roles.values()
                or self.incident['project']!=quality.project.fingerprint()
                or self.original['release']!=self.run.release):
            raise ValueError('controller-assigned technical diagnosis required')
        self.level=next(level for level,actor in roles.items() if actor==self.run.actor)
        reader=getattr(self.board,'diagnostic_resolution',None)
        value=reader(self.run) if reader else {}
        self.resolution=value if isinstance(value,dict) else {}
        self.experiment=None
        self.repair=None
        reader=getattr(self.board,'repair_for_task',None);key=reader(self.incident.get('source')) if reader else None
        if isinstance(key,str):
            from .repairs import reviewed
            self.repair=reviewed(self.q.project,self.store,key)
            if self.store.receipt(key)['binding']['release']!=self.run.release:raise ValueError('foreign corrective diagnosis')

    def actions(self):
        if getattr(self,'resolution',{}).get('role')=='investigate':return ['hold']
        if (self.level=='cto' and self.coverage_correction()
                and self.incident.get('source_state') in ('blocked','triage')
                and self.incident.get('controller_effects')==[]):
            return ['repair_tests','hold']
        if (self.level=='cto' and self.original.get('reviewing') is True
                and self.incident.get('review_escalation') and self.incident.get('resume_allowed') is True):
            return ['return_author','hold']
        repair = (self.level=='cto' and (self.original.get('kind')=='implementation' or self.fixture_correction() and self.repair['context'].get('protocol')=='technical-test-repair-1')
                  and self.original.get('reviewing') is False
                  and self.incident.get('source_state') in ('blocked','triage')
                  and self.incident.get('controller_effects')==[])
        return (['resume'] if self.incident.get('resume_allowed',True) else [])+(['escalate'] if self.level=='lead' else [])+['hold']+(['repair_tests'] if repair else [])

    def repair_freeze(self):
        """Resolve the failed implementation's exact native input, not model prose."""
        if 'repair_tests' not in self.actions():raise ValueError('CTO implementation diagnosis required')
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            source=kb.get_task(conn,self.original['task'])
            if not source or digest(json.loads(source.body))!=self.original['contract']:
                raise ValueError('diagnostic source contract changed')
            key=(self.repair['context']['tests'] if self.original.get('kind')=='tests' and self.fixture_correction()
                else Recovery(self.q.project,self.store,self.board).input(conn,source,'tests'))
        record=self.store.receipt(key,kind='tests_frozen')
        if record['binding']['release']!=self.run.release:raise ValueError('foreign source test freeze')
        frozen=self.q.frozen_plan(record)
        if self.coverage_correction():
            from .test_revision import revision_context
            revision_context(self.q.project,self.store,self.q,self.repair,self.incident['snapshot'],contract=3)
        else:self.q.protect(frozen['snapshot'],self.incident['snapshot'],exact_tests=True)
        return key,frozen

    def coverage_correction(self):
        return (self.original.get('kind')=='tests' and self.original.get('reviewing') is True and self.fixture_correction()
            and self.incident.get('review_escalation')
            and self.repair['context'].get('protocol')=='technical-test-strengthening-1')

    def qa_correction(self):
        return self.original['kind']=='tests' and self.repair and self.repair['proposal']['classification']=='test_contract'

    def fixture_correction(self):
        return self.qa_correction() and self.repair.get('context',{}).get('repair_kind')=='fixture'

    def correction_expectation(self):
        if self.fixture_correction():
            return ('Authorized unpublished fixture revision on the original product baseline. '
                'Missing new product behavior is expected: diagnose fresh Red, not completed implementation. '
                'The candidate may differ from its old freeze only by the independently approved candidate correction; '
                'a changed hash before a new independent freeze is expected, not stale evidence by itself. '
                'Review the full setup/action/assertion diff against the approved scope; reject weakened coverage. Return author corrections within the approved paths; '
                'do not edit the source, demand Green before Red or transfer technical choices to the CEO. '
                'A product-only diagnostic_validate replacement is a disposable SPIKE on a copy; tests and configuration remain exact. '
                'Its result tests a hypothesis and never becomes the author delivery or approval. '
                'Other implementation findings remain visible for the implementation phase and cannot waive any later gate. '
                'The previous implementation snapshot is separate from this test-author baseline. '
                'A failure on this pre-implementation baseline does not prove that a proposed implementation is impossible. '
                'Trace each assertion to its actual client: an HTTP status observed by Python urllib/requests is not a browser console event. '
                'Do not infer a required browser request or status from a separate API probe. '
                'A conflict claim needs evidence that the same required execution cannot satisfy both assertions, not only that an earlier implementation failed. '
                'At CTO level you own the technical ruling; requesting another CTO ruling is not a next action. '
                'diagnostic_validate never alters the author delivery; a fresh delivery_submit and independent test review remain required.')
        return ('Authorized QA expected-text correction, not a new feature Red. The independent corrective plan permits only its listed QA text paths. '
            'Diagnose all frozen-preview failures against the approved brief. Do not tell the author to edit product code or preserve a known incorrect QA expectation; '
            'do not silently override the reviewed authority. diagnostic_validate runs both full suite and QA preview; negative results remain observations, not approval.')

    def deployment_observation(self):
        if self.original['kind']!='integration' or not self.q.project.delivery_roles:return None
        from .deployment import Deployment
        from .intake import Intake
        # Fixed observations, not a model-supplied Docker command or an approval.
        try:
            history=Intake(self.q.project,self.store,self.board).previous(self.run.release)
            return dict(project=self.q.project.fingerprint(),group=self.q.project.namespace+'-homologation',
                **Deployment(self.q.project,self.store,self.board,None).continuity_observation(history))
        except (ValueError,OSError,subprocess.SubprocessError,EffectBlocked) as error:
            return dict(state='unavailable',error=type(error).__name__,delivery_approval=False)

    def evidence(self):
        from .config import execution_context
        result=dict(incident={**self.incident,'workspace':'/workspace','recorded_failure_is_historical':True},failed_execution=self.original,execution=execution_context(self.q.project),
            workspace='/workspace',files=sorted(self.store.manifest(self.incident['snapshot'])),
            allowed_actions=self.actions(),limits='No source writes, approvals, breaker resets or controller repairs. A held incident must state a concrete next technical action.')
        if getattr(self,'resolution',{}):
            previous=self.store.receipt(self.resolution['diagnosis'],kind='diagnostic_decision')
            if previous['payload']['incident']!=self.board.input(self.run,'incident'):
                raise ValueError('resolution must reference its exact held incident')
            experiment_key=previous['payload']['experiment']
            experiment=(self.store.receipt(experiment_key,kind='diagnostic_experiment')
                if experiment_key is not None else None)
            result['diagnostic_capabilities']=dict(observations=['full_suite_report','browser_http_errors_with_path_status_case_context','room_request_response_method_status_context_order'],
                unavailable=['response_bodies','successful_join_response','new_browser_listeners_from_hypothesis'],
                semantics='Hypothesis text never installs instrumentation. Product-only replacements run on a disposable copy; tests stay frozen. A resume authorizes corrective work, not passing tests or delivery. Mixed failures may be repaired incrementally while all gates remain mandatory.')
            result['hold_resolution']=dict(role=self.resolution['role'],previous=previous['payload'],
                observations=(guidance_context([{'experiment':experiment['payload']}])[0]['experiment']
                    if experiment is not None else None),objective=self.resolution['objective'],
                instruction='Reuse the supplied HTTP paths/status/context evidence; do not ask for data already supplied. '
                'Separate observed product faults, unreachable test setup and unresolved hypotheses. '
                'Repeated assertion messages do not establish repeated HTTP requests: correlate the actual events and observer lifetime. '
                'A different experiment must name the unresolved question and expected observation. '
                'Do not whitelist errors, weaken coverage, or send technical choices to the CEO. '
                'CTO must choose the technical alternative now. Use product-only replacements to test a concrete correction, not another unchanged suite merely with a new hypothesis. '
                'Remaining failures do not prohibit resume with bounded implementation guidance; they remain mandatory before submission. '
                'No new HTTP events in later cases is not evidence of missing URLs: inspect observer lifetime and retained messages first.')
            if self.resolution.get('investigation'):
                kb,kbc,_=native()
                with kbc.connect_closing() as conn:
                    task=kb.get_task(conn,self.resolution['investigation']);closed=kb.latest_run(conn,task.id) if task else None
                    if not task or not closed or not closed.ended_at or task.status not in ('done','blocked','triage'):
                        raise ValueError('settled investigation required before technical decision')
                    if task.status=='done':
                        finding=self.store.receipt((closed.metadata or {}).get('diagnosis'),kind='diagnostic_decision')
                        if finding['payload']['incident']!=previous['payload']['incident']:raise ValueError('foreign investigation')
                        result['hold_resolution']['investigation']=finding['payload']
                    else:
                        result['hold_resolution']['investigation_failure']=dict(task=task.id,run=closed.id,
                            outcome=closed.outcome,detail=str(closed.summary or closed.error or 'No completed diagnosis')[:2000],
                            instruction='The investigator failed. CTO owns the remaining diagnosis; do not wait for an impossible completed-parent handoff. No findings were approved.')
        if 'return_author' in self.actions():
            result['review_return']=dict(action='return_author',
                instruction='Return the exact rejected review to its original author for correction, not approval. Choose concrete setup/action guidance within the authorized scope. Require a reachable scenario that isolates the disputed behavior and an independent negative control disabling that specific protection. An unchanged Red baseline that fails earlier does not establish reachability. New author submission and independent freeze/review remain mandatory; never replay an already-used card when that also triggers a different rejection rule.')
        if 'repair_tests' in self.actions():
            key,frozen=self.repair_freeze()
            result['technical_test_repair']=dict(tests=key,cases=frozen['cases'],files=sorted(frozen['tests']),
                contract='The controller resolves the exact frozen tests from the failed implementation. '
                'repair_scope requires test_paths and cases. For explicit additive coverage only, use mode=strengthen and product_imports naming existing root product modules; prior assertions/statements must remain unchanged and additions are appended in scoped cases. No receipt IDs. '
                'Diagnose 404/roster failures by origin before classifying them as test defects. '
                'Do not whitelist console messages or turn error observers off. A deliberate negative API probe '
                'may use the same browser context request client, preserving cookies. '
                'A tie test requires a deterministic reachable tie setup, not merely an assertion on an impossible deal. '
                'Preserve approved behavior. Repair requires an actual experiment and independent author review/freezing; '
                'if the evidence is inconclusive, record hold with a bounded next experiment.')
            kb,kbc,_=native()
            with kbc.connect_closing() as conn:
                task=kb.get_task(conn,self.run.task)
                requested=json.loads(task.body or '{}').get('test_repair_scope') if task else None
            if requested:
                if requested['tests']!=key:raise ValueError('requested repair freeze differs from failed implementation input')
                frozen=self.q.frozen_plan(self.store.receipt(requested['tests'],kind='tests_frozen'))
                previous=self.store.receipt(requested['previous_diagnosis'],kind='diagnostic_decision')
                result['technical_test_repair'].update(previous=previous['payload'],
                    contract='Use a current diagnostic_validate experiment. If a technical test defect is demonstrated, '
                    'end with repair_tests and repair_scope containing test_paths and cases; the controller resolves the tests receipt. '
                    'Preserve accepted product behavior, assertion expressions and browser error observers. '
                    'A deliberate negative HTTP API probe may use the same browser context request client to preserve cookies '
                    'without injecting an expected network error into the UI console. Never ignore console errors globally. '
                    'This authorizes only scoped author correction and fresh independent freeze, not delivery. '
                    'If evidence does not support a technical test repair, hold with concrete findings.')
        result['phase_expectation']=(
            'Tests author: add new acceptance tests for the current increment before its product implementation. '
            'Existing baseline tests may all pass; this is expected regression protection, not an impediment to resuming test authorship. '
            'A passing diagnostic on an unchanged baseline does not mean new tests cannot produce Red. '
            'Never ask the author to make old frozen tests fail, weaken them, or modify product behavior to manufacture Red. '
            'New test assertion failures are expected Red; new test errors need author repair. '
            'Resume authoring may precede Red; Red and independent test freeze remain mandatory before implementation. '
            'For an output-budget failure, separate the request-policy defect from the unfinished test work; '
            'small complete tool calls can continue within the authorized cap once the transport precondition is corrected.'
            if self.original['kind']=='tests' and not self.original['reviewing'] else
            'Review the existing immutable handoff; do not reproduce Red or edit the author.'
            if self.original['reviewing'] else
            'Diagnose the current implementation/integration phase; preserve frozen tests and its existing delivery gates.')
        # The source execution is no longer claimed. Read its immutable contract,
        # not diagnostic-card inputs, and revalidate the maintenance authority.
        kb,api,_=native()
        with api.connect_closing() as conn:
            source=kb.get_task(conn,self.incident['source'])
            source_body=json.loads(source.body or '{}') if source else {}
        package=source_package_context(source_body,self.original)
        if package:result['failed_work_package']=package
        maintenance_key=source_body.get('inputs',{}).get('maintenance_review')
        if maintenance_key:
            from .maintenance import reviewed,context
            if digest(source_body)!=self.original['contract'] or source_body.get('release')!=self.run.release:
                raise ValueError('exact maintenance source contract required')
            reviewed(self.q.project,self.store,maintenance_key)
            review=self.store.receipt(maintenance_key,kind='plan_review')
            if review['binding']['release']!=self.run.release:
                raise ValueError('foreign maintenance diagnosis')
            plan=self.store.receipt(review['payload']['plan'],kind='work_plan')
            result['maintenance']=context(self.q.project,self.store,plan['payload']['approval'])
            result['phase_expectation']=(
                'Scoped maintenance of existing tests, not new feature authorship. '
                'The operator edit_contract and exact paths override conflicting historical plan prose. '
                'Do not require new assertions or a new Red against correct delivered behavior. '
                'Historical Red remains provenance; fresh full original and revised suites, independent freeze, '
                'Green and negative controls remain mandatory. The author must edit only the authorized fixture '
                'helpers and call delivery_submit, which runs the controller browser harness. '
                'fabriquinha_acceptance is injected by that harness; its absence in the exploratory shell '
                'does not justify editing or creating the framework. A passing diagnostic is not delivery approval. '
                'Preserve allowed_actions; do not reset exhausted retries or grant a new retry from this context.')
        result['experiment_semantics']='A complete diagnostic report may contain failures, errors or skips. These are evidence for guidance, not a delivery approval. Resume permits a fresh attempt in the same phase; it does not certify success.'
        if self.qa_correction():
            from .repairs import context_view
            result['repair_authority']={**self.repair,'context':context_view(self.store,self.repair['context'])}
            preserved=self.repair['context'].get('implementation_snapshot')
            if preserved:
                result['preserved_implementation']=dict(snapshot=preserved,
                    files={p:meta for p,meta in self.store.manifest(preserved).items() if '/' not in p and p.endswith('.py') and meta['bytes']<=131072},
                    instruction='Use diagnostic_report with implementation_path and offset=0 to inspect this immutable product source. Follow next_offset. The current /workspace is the Red baseline and may intentionally lack these functions. Reading retained code never grants approval or replaces a current experiment.')

            reviewed=self.store.receipt(self.repair['review'])
            if reviewed['kind'] in ('test_repair_admission','fixture_author_admission'):
                kb,api,_=native()
                with api.connect_closing() as conn:
                    source=kb.get_task(conn,self.incident['source'])
                    body=json.loads(source.body) if source else {}
                if digest(body)!=self.original['contract'] or body.get('release')!=self.run.release:
                    raise ValueError('exact corrective source contract required for brief context')
                reviewed=self.store.receipt(body['release_plan'],kind='plan_review')
            elif reviewed['kind']!='plan_review':raise ValueError('scoped corrective authority required')
            approval=self.store.receipt(reviewed['payload']['plan'],kind='work_plan')['payload'].get('approval')
            if isinstance(approval,str):
                from .intake import Intake
                result['approved_brief']=Intake(self.q.project,self.store,self.board).approved(approval)[1]['payload']['document']
            result['phase_expectation']=self.correction_expectation()
        if self.incident.get('control_refusal'):
            from .quality import CONTROL_SUBMISSION_CONTRACT
            result['last_control_refusal']=control_refusal_context(self.store,self.q.project,self.original,
                self.incident['control_refusal'],self.incident['snapshot'])
            result['control_submission_contract']=CONTROL_SUBMISSION_CONTRACT
            result['experiment_semantics']+=' For a control refusal, a passing unmodified suite only reconfirms Green; it does not resolve missing mutation targets. Address the recorded negative-control coverage in the technical guidance.'
        historical=[]
        for f in (self.store.root/'receipts').glob('*.json'):
            record=self.store.receipt(f.stem)
            scope=record['binding']
            if (record['kind']=='submission_refusal' and scope.get('task')==self.original['task']
                    and scope.get('contract')==self.original['contract'] and scope.get('release')==self.original['release']
                    and scope.get('number',0)<self.original['number']):
                historical.append((scope['number'],f.stem,scope))
        if historical:
            result['historical_submission_refusals']=[dict(source_run=n,**submission_refusal_context(
                self.store,self.q.project,scope,key,self.incident['snapshot'])) for n,key,scope in sorted(historical)[-3:]]
        if self.incident.get('submission_refusal'):
            result['last_submission_refusal']=submission_refusal_context(self.store,self.q.project,self.original,self.incident['submission_refusal'],self.incident['snapshot'])
        if self.incident.get('suite_refusal'):
            result['last_suite_refusal']=suite_refusal_context(self.store,self.q.project,self.original,
                self.incident['suite_refusal'],self.incident['snapshot'])
        if self.incident.get('browser_refusal'):
            result['last_browser_refusal']=browser_refusal_context(self.store,self.q.project,self.original,self.incident['browser_refusal'])
            result['browser_limits']='A green unittest experiment cannot establish deployed QA success. Use the actual browser error; do not repeat unchanged QA as a substitute for code/contract diagnosis.'
        if self.incident.get('review_escalation'):
            escalation=self.store.receipt(self.incident['review_escalation'],kind='review_escalation')['payload']
            result['review_feedback']=self.store.receipt(escalation['review'])['payload']['verdict']
            if escalation.get('recurrence'):
                result['review_recurrence']=escalation['recurrence']
                result['impasse_contract']='Three consecutive independent change requests concern the same files. Diagnose whether the current issue is an unresolved defect, conflicting instructions or a tool limitation. This is not a root-cause verdict, approval or permission to weaken tests. CTO owns resolution of conflicting technical review instructions using the actual protocol and complete evidence. Guidance may explain aggregate coverage or request a new author revision of unfrozen candidate files; it cannot waive accepted behavior, baseline tests, CI or independent review. Do not transfer this technical decision to the CEO. Resume keeps independent review mandatory; hold if no permitted operation can resolve the issue.'
            from .browser import author_protocol
            result['browser_protocol']=author_protocol()
            if self.original['kind']=='tests' and not self.qa_correction():
                review=self.store.receipt(escalation['review'],kind='test_review')
                red=self.q.test_evidence(review['payload']['red'])
                baseline=self.q.tests(red['payload']['baseline']);candidate=self.q.tests(self.incident['snapshot'])
                result['test_revision_contract']=dict(protected_baseline=red['payload']['baseline'],protected_paths=sorted(baseline),
                    candidate_only_paths=sorted(set(candidate)-set(baseline)),
                    rule='The current tests are not frozen yet. Only the original tests author may revise candidate-only paths after changes are requested, followed by another independent review. Diagnostic SPIKE refusal to rewrite tests limits this diagnostic phase, not the author. Baseline tests stay protected. Do not request duplicate criterion IDs; evaluate coverage together with the complete unittest/browser suite and retained QA.')
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            body=json.loads(kb.get_task(conn,self.run.task).body)
            if body.get('review_experiment'):
                result['review_experiment']=body['review_experiment']
                result['phase_expectation']+=' Use diagnostic_validate with product-only replacements on a disposable copy when needed to test feasibility. No source/test changes or delivery approval. End with hold and concrete findings; controller admission permits succession to independent delivery review.'
            if self.incident.get('review_escalation') and self.original['kind']=='tests' and self.q.project.delivery_roles:
                source=json.loads(kb.get_task(conn,self.original['task']).body)
                if digest(source)!=self.original['contract']:raise ValueError('diagnostic source contract changed')
                result['required_browser_criteria']=source['criteria']
                result['coverage_contract']='Every assigned criterion needs a representative deployed check ID; do not advise removing a required ID. Behavioral coverage is assessed across the full unittest/browser suite and all retained/new QA, not solely that one check. No duplicate IDs. New candidate paths may be revised by the author before freeze. Scope/architecture decisions belong to technical reviewers, never the CEO.'
            if body.get('escalated_from'):
                prior=kb.latest_run(conn,body['escalated_from'])
                history=dict(historical_only=True,grants_authority=False,task=body['escalated_from'],
                    state=getattr(prior,'outcome',None))
                if prior and prior.metadata and prior.metadata.get('diagnosis'):
                    key=prior.metadata['diagnosis'];receipt=self.store.receipt(key,kind='diagnostic_decision');data=receipt['payload']
                    if (data['incident']!=self.board.input(self.run,'incident') or data['project']!=self.q.project.fingerprint()
                            or receipt['binding']['task']!=body['escalated_from'] or receipt['binding']['number']!=prior.id
                            or receipt['binding']['kind']!='diagnostic' or receipt['binding']['release']!=self.run.release):
                        raise ValueError('previous diagnosis must match exact scoped predecessor')
                    history.update(receipt=key,binding=receipt['binding'],action=data['action'],experiment=None)
                    if data.get('experiment'):
                        experiment=self.store.receipt(data['experiment'],kind='diagnostic_experiment')
                        if experiment['binding']!=receipt['binding'] or experiment['payload']['incident']!=data['incident']:
                            raise ValueError('historical experiment must match its diagnosis')
                        history['experiment']=dict(receipt=data['experiment'],snapshot=experiment['payload']['snapshot'],report=experiment['payload']['report'])
                # Free-form historical verdicts remain in immutable receipts.
                # Handoffs carry observed evidence, not their old imperatives.
                result['previous_diagnosis']=history
        observed=self.deployment_observation()
        if observed is not None:result['deployment_observation']=observed
        result['evidence_priority']='Historical decisions grant no authority and may be wrong or obsolete. Reassess this incident using the current tool contract, current observations and a fresh SPIKE. Preserve actual mismatches; do not inherit a prior instruction merely because a previous agent wrote it.'
        return result

    def validate(self,args):
        self.board.ensure(self.run)
        document_kind=self.incident.get('document_kind')
        field='document' if document_kind else 'replacements'
        if (not isinstance(args,dict) or not {'hypothesis'}<=set(args) or set(args)-{'hypothesis',field}
                or not isinstance(args['hypothesis'],str) or not 1<=len(args['hypothesis'].strip())<=2000):
            raise ValueError('bounded experiment hypothesis and optional '+field+' required')
        snapshot=self.incident['snapshot']
        if document_kind:
            from .intake import brief,plan
            tree=self.store.tree(snapshot)
            candidate=args.get('document',json.loads((tree/'document.json').read_bytes()))
            if len(encoded(candidate))>64000:raise ValueError('bounded diagnostic document required')
            try:
                if document_kind=='brief':brief(candidate)
                elif document_kind=='plan':plan(candidate,json.loads((tree/'approved_brief.json').read_bytes()),self.q.project)
                else:raise ValueError('unknown document validator')
                report=dict(valid=True,error=None)
            except ValueError as error:report=dict(valid=False,error=str(error)[:2000])
            self.experiment=self.q.record(self.run,'diagnostic_experiment',dict(incident=self.board.input(self.run,'incident'),
                snapshot=snapshot,hypothesis=args['hypothesis'],validator=document_kind,document=candidate,report=report))
            return dict(experiment=self.experiment,report=report,delivery_approval=False)
        correction=self.qa_correction() and not self.fixture_correction()
        if 'replacements' in args:
            if correction:
                with tempfile.TemporaryDirectory(prefix='.diagnostic-qa-',dir=self.store.root.parent) as folder:
                    work=Path(folder);self.store.checkout(snapshot,work)
                    replacements=args['replacements']
                    if (not isinstance(replacements,dict) or not replacements
                            or not set(replacements)<=set(self.repair['proposal']['test_paths'])
                            or any(not isinstance(v,str) or len(v)>131072 for v in replacements.values())):
                        raise ValueError('diagnostic correction may propose only authorized QA expected-text files')
                    for path,content in replacements.items():(work/path).write_text(content)
                    snapshot=self.store.capture(work)
                self.q.correction_diff(self.repair['context']['snapshot'],snapshot,self.repair['proposal']['test_paths'])
            else:
                replacements=args['replacements']
                if isinstance(replacements,dict) and 1<=len(replacements)<=16 and all(isinstance(p,str) for p in replacements):
                    manifest=self.store.manifest(snapshot)
                    protected=sorted(p for p in replacements if p in manifest and any(p==prefix or p.startswith(prefix)
                        for prefix in (*PROTECTED,self.q.project.tests_dir+'/')))
                    if protected:
                        refusal=self.q.record(self.run,'diagnostic_refusal',dict(incident=self.board.input(self.run,'incident'),snapshot=snapshot,
                            classification='operation_forbidden',phase='diagnostic',paths=protected,
                            next_operation='diagnostic_validate_without_replacements',delivery_approval=False))
                        raise ValueError('protected baseline changed: '+protected[0]+'. operation_forbidden in diagnostic SPIKE, not infrastructure failure; no source edit was made. '
                            'Next permitted operation: diagnostic_validate with a hypothesis only, without replacements, to observe the immutable current suite. '
                            'Assertion failures qualify diagnostic evidence, not Green or approval. Candidate-only author changes require a new author revision and independent review. Refusal '+refusal)
                snapshot=product_mutations(self.q,snapshot,[replacements])[0]
        job,report=DeliveryTools.wait(self,lambda:self.q.observe(self.run,snapshot,'green' if correction else 'diagnostic'))
        observed=self.deployment_observation();extra={} if observed is None else dict(deployment_observation=observed)
        events=getattr(self.q,'validation_progress',[])
        if isinstance(events,list):
            http=[event for event in events if isinstance(event,dict) and event.get('event') in ('http_error','room_request','room_response','room_request_failed')][-256:]
            if http:extra['http_observations']=dict(job=job,events=http,semantics='Bounded tail of sandbox events, not a complete network capture or approval. Absence of an event does not prove absence of a request. Correlate case, context, timestamps and source; never whitelist unexplained errors.')
        self.experiment=self.q.record(self.run,'diagnostic_experiment',dict(incident=self.board.input(self.run,'incident'),
            snapshot=snapshot,source_snapshot=self.incident['snapshot'],hypothesis=args['hypothesis'],job=job,report=report,**extra))
        result=dict(experiment=self.experiment,report=report,delivery_approval=False,
                    **self.review_probe_feedback(),**extra)
        if len(json.dumps(result))>6000:
            return dict(experiment=self.experiment,job=job,tests_run=report.get('tests_run'),
                failures=len(report.get('failures',[])),errors=len(report.get('errors',[])),
                qa_status=report.get('qa_preview',{}).get('status'),
                http_errors=[e for e in extra.get('http_observations',{}).get('events',[])
                    if e.get('event') in ('http_error','room_request_failed')][:4],
                observation_limits='At most 128 priority events and 256 total retained; summary shows first 4 errors. Full raw output remains in the job archive. Absence does not prove no errors.',
                report_access='Call diagnostic_report with offset=0 and follow next_offset. Full immutable report is retained by the controller; do not use host/cache paths.',
                delivery_approval=False)
        return result

    def citable_experiment(self,key):
        """Resolve a fact reference; never promote it to current execution authority."""
        receipt=self.store.receipt(key,kind='diagnostic_experiment')
        if receipt['binding']!=self.run.binding():
            data=receipt['payload'];binding=receipt['binding']
            if (binding.get('kind')!='diagnostic' or binding.get('release')!=self.run.release
                    or data.get('incident')!=self.board.input(self.run,'incident')
                    or data.get('source_snapshot',data.get('snapshot'))!=self.incident['snapshot']):
                raise ValueError('foreign experiment: same incident, release and source snapshot required')
        return receipt


    def report_page(self,args):
        self.board.ensure(self.run)
        if (not isinstance(args,dict) or not {'offset'}<=set(args) or set(args)-{'offset','experiment','implementation_path'} or type(args['offset']) is not int or args['offset']<0):
            raise ValueError('nonnegative integer offset required')
        if 'implementation_path' in args:
            if 'experiment' in args:raise ValueError('choose a report or preserved implementation, not both')
            context=(self.repair or {}).get('context',{})
            snapshot=context.get('implementation_snapshot')
            if not snapshot:raise ValueError('no authorized preserved implementation for this incident')
            manifest=self.store.manifest(snapshot);path=args['implementation_path']
            if (not isinstance(path,str) or path not in manifest or '/' in path or not path.endswith('.py')
                    or manifest[path]['bytes']>131072):
                raise ValueError('bounded existing root Python product file required')
            text=(self.store.tree(snapshot)/path).read_text();offset=args['offset']
            if offset>len(text):raise ValueError('offset beyond preserved implementation')
            end=min(offset+1800,len(text))
            return dict(snapshot=snapshot,path=path,sha256=manifest[path]['sha256'],offset=offset,
                line_start=text[:offset].count('\n')+1,total=len(text),text=text[offset:end],
                next_offset=end if end<len(text) else None,delivery_approval=False,
                semantics='Preserved implementation evidence only; not the test-author baseline, current experiment or approval.')
        key=args.get('experiment',self.experiment)
        if not key:raise ValueError('provide a retained experiment receipt or run diagnostic_validate')
        receipt=self.citable_experiment(key)

        text=json.dumps(receipt['payload'],ensure_ascii=True)
        offset=args['offset']
        if offset>len(text):raise ValueError('offset beyond report')
        end=min(offset+1800,len(text))
        report=receipt['payload'].get('report',{})
        summary=dict(tests_run=report.get('tests_run'),failures=len(report.get('failures',[])),
            errors=len(report.get('errors',[])),qa_status=report.get('qa_preview',{}).get('status'),
            qa_failure_kind=report.get('qa_preview',{}).get('failure_kind'),
            qa_errors=[str(error)[:1200] for error in report.get('qa_preview',{}).get('errors',[])[:4]])
        return dict(experiment=key,summary=summary,offset=offset,total=len(text),text=text[offset:end],
                    next_offset=end if end<len(text) else None,delivery_approval=False)

    def review_probe_feedback(self):
        """Expose succession admission before the CTO ends its live activity.

        This is the same gate used by the reconciler, not approval or a new
        transition. A genuine hold remains possible; no identical retry is
        scheduled by this feedback.
        """
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            task=kb.get_task(conn,self.run.task)
            body=json.loads(task.body or '{}')
        probe=body.get('review_experiment')
        if not probe:return {}
        from .repairs import review_reassessment
        try:
            review_reassessment(self.q.project,self.store,self.board.input(self.run,'incident'),
                self.board.input(self.run,'held_review'),probe['handoff'],self.experiment)
        except ValueError as error:
            return dict(review_reassessment=dict(eligible=False,reason=str(error),
                next_action='Inspect this admission refusal before ending. If feasible, use diagnostic_validate with product-only replacements on a disposable copy to reach the disputed behavior; preserve every test/configuration. Do not repeat the unchanged suite or request an identical Red. If no justified experiment is feasible, hold with that concrete limitation; succession will remain blocked.',
                delivery_approval=False))
        return dict(review_reassessment=dict(eligible=True,
            next_action='Record the experiment findings. Controller admission permits independent delivery review; this does not freeze tests or approve delivery.',delivery_approval=False))

    @property
    def quality(self):return self.q  # Reuse the bounded fixed-job observation helper.

    def decide(self,args):
        self.board.ensure(self.run)
        expected={'action','reason','findings'}
        if isinstance(args,dict) and args.get('action')=='repair_tests':expected.add('repair_scope')
        if isinstance(args,dict) and args.get('action')=='return_author':expected.add('verification')
        scoped_hold=bool(getattr(self,'resolution',{})) and isinstance(args,dict) and args.get('action')=='hold'
        if scoped_hold:expected.add('next_step')
        executable=getattr(self,'resolution',{}).get('protocol')=='executable-decision-1'
        if executable:expected.add('ruling')
        if (not isinstance(args,dict) or set(args)!=expected
                or args['action'] not in self.actions()):
            raise ValueError('permitted technical actions: '+', '.join(self.actions())+'; required fields for this action: '+', '.join(sorted(expected))+'; missing fields: '+', '.join(sorted(expected-set(args) if isinstance(args,dict) else expected))+'; unexpected fields: '+', '.join(sorted(set(args)-expected) if isinstance(args,dict) else [])+'; preserve native triage and never send technical decisions to CEO')
        if args['action']=='return_author':
            verification=args['verification']
            if (not isinstance(verification,dict) or set(verification)!={'reachable_scenario','negative_control'}
                    or any(not isinstance(v,str) or not 1<=len(v.strip())<=2000 for v in verification.values())):
                raise ValueError('author return requires reachable scenario and specific negative control obligations')
        if executable:
            ruling=args['ruling']
            if (not isinstance(ruling,dict) or set(ruling)!={'choice','correction','remaining','blocker'}
                    or ruling['blocker'] not in ('none','infrastructure','missing_evidence','tool_capability')
                    or any(not isinstance(ruling[k],str) or not 1<=len(ruling[k].strip())<=2000 for k in ('choice','correction','remaining'))):
                raise ValueError('executable ruling requires chosen alternative, bounded correction, remaining obligations and classified blocker')
            if args['action']=='hold' and ruling['blocker']=='none':
                raise ValueError('hold requires an actual unmet dependency; technical choice belongs to this CTO activity; use resume for demonstrated partial corrections')
        if scoped_hold:
            step=args['next_step']
            if (not isinstance(step,dict) or set(step)!={'owner','operation','expected_evidence','precondition'}
                    or step['owner'] not in self.q.project.technical_roles.values()
                    or any(not isinstance(step[k],str) or not 1<=len(step[k].strip())<=1200 for k in ('operation','expected_evidence','precondition'))):
                raise ValueError('scoped hold requires a technical owner, concrete operation, expected evidence and unmet precondition')
        if args['action'] in ('resume','return_author') and self.experiment is None:
            raise ValueError('resume requires a real experiment in this execution')
        snapshot=self.incident['snapshot']
        if (not isinstance(args['reason'],str) or not 1<=len(args['reason'].strip())<=2000
                or not isinstance(args['findings'],list) or not 1<=len(args['findings'])<=8):
            raise ValueError('concrete bounded technical reason and findings required')
        files=[]
        for finding in args['findings']:
            if isinstance(finding,dict) and set(finding)=={'evidence','detail'}:
                evidence=finding['evidence']
                if (not isinstance(evidence,str)
                        or evidence=='experiment' and self.experiment is None
                        or not isinstance(finding['detail'],str) or not 1<=len(finding['detail'].strip())<=2000):
                    raise ValueError('finding must cite incident, current experiment, or an exact retained experiment receipt')
                if evidence not in ('incident','experiment'):
                    self.citable_experiment(evidence)
            else:files.append(finding)
        if (args['action']=='resume' and self.qa_correction()
                and any(f.get('path') not in self.repair['proposal']['test_paths'] for f in files)):
            raise ValueError('resume guidance cannot require writes outside the independently authorized QA paths; cite other observations as incident/experiment evidence')
        if files:review_decision(dict(decision='changes',reason=args['reason'],findings=files),self.store.manifest(snapshot),self.store.tree(snapshot))
        verdict=dict(decision='changes',reason=args['reason'],findings=args['findings'])
        repair=None
        if args['action']=='repair_tests':
            from .technical_repair import validate_scope
            if self.experiment is None:raise ValueError('test repair requires a current CTO experiment')
            scope=args['repair_scope'];key,_=self.repair_freeze()
            allowed={'test_paths','cases'}|({'mode','product_imports'} if isinstance(scope,dict) and scope.get('mode')=='strengthen' else set())
            if (not isinstance(scope,dict) or set(scope) not in (allowed,allowed|{'tests'})
                    or 'tests' in scope and scope['tests']!=key):
                raise ValueError('repair_scope must contain test_paths and cases only; the controller resolves the source freeze; legacy tests must match that exact receipt')
            if self.original['kind']=='tests':
                if scope.get('mode')!='strengthen':raise ValueError('failed strict test repair requires explicit strengthening authority')
                scope={**scope,'parent_repair':self.repair['review']}
            repair=validate_scope(self.q.project,self.store,self.board.input(self.run,'incident'),
                                  self.run.binding(),self.experiment,{**scope,'tests':key})
        receipt=self.q.record(self.run,'diagnostic_decision',dict(incident=self.board.input(self.run,'incident'),
            action=args['action'],verdict=verdict,experiment=self.experiment,delivery_approval=False,
            **({'next_step':args['next_step']} if scoped_hold else {}),
            **({'ruling':args['ruling']} if executable else {}),
            **({'verification':args['verification']} if args['action']=='return_author' else {}),
            **({'test_repair':repair} if repair else {})))
        self.sandbox.close()
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            if not kb.complete_task(conn,self.run.task,summary=verdict['reason'],metadata={'diagnosis':receipt},
                                    expected_run_id=self.run.number):
                raise ValueError('native diagnostic completion refused')
        return dict(status='diagnosis_completed',action=args['action'],diagnosis=receipt,delivery_approval=False)


class Recovery:
    def __init__(self,project,store,board):
        self.project,self.store,self.board=project,store,board
        self.journal=Journal(store.root/'effects')

    def cards(self,conn):
        kb,_,_=native()
        return [kb.get_task(conn,row[0]) for row in conn.execute('SELECT id FROM tasks ORDER BY created_at,id')]

    def stage_for(self,reviewing,actor):
        return 'cto' if reviewing or actor==self.project.technical_roles['lead'] else 'lead'

    def expired_effects(self,task):
        result=[]
        for path in self.journal.root.glob('*.json'):
            effect=json.loads(path.read_bytes());identity=effect.get('identity',{})
            binding=identity.get('binding',{}) if isinstance(identity,dict) else {}
            if (isinstance(binding,dict) and binding.get('task')==task and effect.get('state')!='done'
                    and (effect.get('state')=='blocked' or effect.get('deadline',float('inf'))<=time.time())):result.append(path.stem)
        return result

    def guidance(self,run):
        """Resolve full applied guidance; native prose may be length-capped."""
        if not self.project.technical_roles or run.kind=='diagnostic':return []
        self.board.ensure(run);_,api,_=native();result=[]
        with api.connect_closing() as conn:
            rows=conn.execute("SELECT author,body FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %' ORDER BY id DESC LIMIT 2",(run.task,)).fetchall()
        for row in reversed(rows):
            if row['author'] not in self.project.technical_roles.values():continue
            key=row['body'].split(' ',2)[1];record=self.store.receipt(key,kind='diagnostic_decision')
            incident=self.store.receipt(record['payload']['incident'],kind='incident')
            scope=incident['binding']
            if (record['binding']['actor']!=row['author'] or record['binding']['kind']!='diagnostic'
                    or record['payload']['project']!=self.project.fingerprint() or record['payload']['action'] not in ('resume','return_author')
                    or any(scope[k]!=getattr(run,k) for k in ('task','kind','author','release','contract')) or scope['number']>=run.number):
                raise ValueError('diagnostic guidance belongs to another phase, owner or execution')
            # A completed implementation may now be in independent QA/review.
            # Prior-phase advice is historical context, never a veto or new authority.
            returned=record['payload']['action']=='return_author' and scope['reviewing'] and not run.reviewing and run.actor==scope['author']
            if not returned and (scope['reviewing']!=run.reviewing or scope['actor']!=run.actor):continue
            experiment=self.store.receipt(record['payload']['experiment'],kind='diagnostic_experiment')
            if experiment['binding']!=record['binding'] or experiment['payload']['incident']!=record['payload']['incident']:
                raise ValueError('diagnostic guidance lacks its exact experiment')
            result.append(dict(receipt=key,verdict=record['payload']['verdict'],experiment=experiment['payload'],
                **({'required_verification':record['payload']['verification']} if record['payload']['action']=='return_author' else {})))
        return result

    def handoff(self,conn,task):
        row=conn.execute("SELECT e.payload,r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(task.id,)).fetchone()
        return (json.loads(row['payload']),json.loads(row['metadata'] or '{}')) if row else ({},{})

    def input(self,conn,task,name):
        """Controller read of an inactive task, never authority for a worker."""
        value=json.loads(task.body).get('inputs',{}).get(name)
        if isinstance(value,str) and value.startswith('parent:'):
            _,parent,key=value.split(':',2)
            if not conn.execute('SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?',(parent,task.id)).fetchone():
                raise ValueError('diagnosis requires the actual parent handoff')
            _,metadata,_=self.board.closed_review(parent);value=metadata.get(key)
        if not isinstance(value,str) or value.startswith('parent:'):raise ValueError('diagnostic input missing: '+name)
        return value

    def snapshot(self,conn,task,source,handoff):
        if source.kind in ('brief','plan'):
            from .intake import Intake
            documents={'task.json':json.loads(task.body),'document.json':{}}
            proposal=handoff.get('plan' if source.kind=='plan' else 'request')
            if proposal:
                record=self.store.receipt(proposal)
                if record['kind'] in ('product_brief','work_plan'):
                    origin=source.binding();origin.update(actor=source.author,reviewing=False)
                    if (not Run(**origin).same_subject(record['binding']) or record['payload']['project']!=self.project.fingerprint()):
                        raise ValueError('document incident must match its actual author and contract')
                    documents['document.json']=record['payload']['document']
            if source.kind=='plan':
                approval,brief=Intake(self.project,self.store,self.board).approved(self.input(conn,task,'approved_brief'))
                if approval['binding']['release']!=source.release:raise ValueError('foreign business approval in diagnostic')
                documents['approved_brief.json']=brief['payload']['document']
            with tempfile.TemporaryDirectory(prefix='.recovery-context-',dir=self.store.root.parent) as folder:
                for name,data in documents.items():write_json(Path(folder)/name,data)
                return self.store.capture(Path(folder))
        if source.kind=='integration':
            if source.reviewing:
                rollout=self.store.receipt(handoff['rollout'],kind='rollout')
                from .qa_recovery import origin
                prior=origin(self.project,self.store,source)
                expected={**prior.binding(),'actor':source.author,'reviewing':False}
                if (not Run(**expected).same_subject(rollout['binding'])
                        or rollout['payload']['project']!=self.project.fingerprint()):raise ValueError('foreign deployed QA handoff')
                record=self.store.receipt(rollout['payload']['candidate'],kind='artifact')
            else:
                record=self.store.receipt(self.input(conn,task,'delivery'),kind='delivery_review')
                verdict=record['payload']['verdict']
                if (record['binding']['kind']!='implementation' or record['binding']['reviewing'] is not True
                        or record['binding']['actor'] not in self.project.reviewers_for(record['binding']['author'])
                        or verdict['decision']!='approve' or verdict['findings']):raise ValueError('approved independent delivery required for integration diagnosis')
            if record['payload']['project']!=self.project.fingerprint() or record['binding']['release']!=source.release:
                raise ValueError('foreign integration snapshot')
            self.store.tree(record['payload']['snapshot']);return record['payload']['snapshot']
        if source.reviewing:
            kind='red' if source.kind=='tests' else 'green'
            record=(Quality(self.project,self.store,None,self.board).test_evidence(handoff[kind]) if kind=='red'
                    else self.store.receipt(handoff[kind],kind=kind))
            expected=Run(**{**source.binding(),'actor':source.author,'reviewing':False})
            body=json.loads(task.body)
            if digest(body)!=source.contract:raise ValueError('diagnostic source contract changed')
            authority=body.get('inputs',{}).get('reassessment_review')
            if authority and not expected.same_subject(record['binding']):
                from .repairs import reassessment_origin
                expected=reassessment_origin(self.project,self.store,source,authority,handoff[kind])
            if (not expected.same_subject(record['binding']) or record['payload']['project']!=self.project.fingerprint()):
                raise ValueError('review diagnostic must match its exact immutable author handoff')
            return record['payload']['snapshot']
        return self.store.capture(Path(task.workspace_path))

    def coordinate_hold(self,conn,task,decision_key):
        """One evidence-directed native pair, never recursive generic diagnoses."""
        kb,_,_=native();body=json.loads(task.body)
        decision=self.store.receipt(decision_key,kind='diagnostic_decision');data=decision['payload']
        latest=kb.latest_run(conn,task.id)
        review_followup=(not body.get('hold_resolution') and body.get('stage')=='cto'
            and self.store.receipt(data['incident'],kind='incident')['payload'].get('review_escalation'))
        followup=(body.get('hold_resolution',{}).get('protocol')=='evidence-directed-hold-1'
                  and body['hold_resolution'].get('role')=='decide')
        if (body.get('stage')!='cto' or (not followup and not review_followup and (not body.get('test_repair_scope') or body.get('hold_resolution')))
                or task.status!='done' or not latest or (latest.metadata or {}).get('diagnosis')!=decision_key
                or not latest.ended_at or latest.outcome!='completed'
                or task.assignee!=self.project.technical_roles['cto']
                or decision['binding']['actor']!=task.assignee or decision['binding']['kind']!='diagnostic'
                or decision['binding']['reviewing'] is not False or decision['binding']['release']!=body['release']
                or decision['binding']['task']!=task.id or decision['binding']['number']!=latest.id
                or decision['binding']['contract']!=digest(body) or data.get('action')!='hold'
                or data.get('project')!=self.project.fingerprint() or not data.get('experiment')):
            raise ValueError('exact completed scoped CTO hold required')
        incident=self.store.receipt(data['incident'],kind='incident');facts=incident['payload'];source=kb.get_task(conn,facts['source'])
        run=kb.latest_run(conn,source.id) if source else None
        experiment=self.store.receipt(data['experiment'],kind='diagnostic_experiment')
        settled_states=('blocked','triage') if review_followup else ('blocked',)
        if (data['incident']!=body['inputs']['incident'] or not source or source.status not in settled_states
                or not run or not run.ended_at or run.id!=facts['source_run']
                or digest(json.loads(source.body))!=incident['binding']['contract']
                or self.store.capture(source.workspace_path)!=facts['snapshot']
                or self.expired_effects(source.id)
                or experiment['binding']!=decision['binding'] or experiment['payload']['incident']!=data['incident']):
            raise ValueError('unchanged settled source and exact evidence required')
        pair=[]
        protocol='review-author-return-1' if review_followup else 'executable-decision-1' if followup else 'evidence-directed-hold-1'
        stages=(('decide','cto','Choose a technical alternative and bounded corrective work now. Reuse prior evidence. A hypothesis cannot add instrumentation. Test a concrete product-only correction on the disposable snapshot when useful; preserve all frozen tests. Resume may return partial corrections to the author while remaining failures stay mandatory. Hold only for a concrete missing capability, evidence or infrastructure dependency; never request another CTO choice.'),) if followup or review_followup else (
            ('investigate','lead','Use the existing observations and source to isolate unresolved causes. Distinguish original HTTP errors from repeated observer assertions. Investigate the unexplained setup/synchronization failure with a bounded hypothesis; record findings and the exact next technical operation, not delivery approval.'),
            ('decide','cto','Use the preceding investigation and retained evidence to choose executable corrective guidance. Decide a reachable deterministic setup for the approved behavior without weakening coverage. Separate product correction from scoped test repair. Use resume or repair_tests when justified; a hold must identify a specific unmet precondition, owner and next operation, not delegate technical choice back to CTO/CEO.'))
        for role,stage,objective in stages:
            resolution=dict(protocol=protocol,role=role,diagnosis=decision_key,objective=objective)
            parent=task.id
            if pair:
                investigation=kb.get_task(conn,pair[0]);closed=kb.latest_run(conn,pair[0])
                if (investigation.status not in ('done','blocked','triage') or not closed or not closed.ended_at
                        or self.expired_effects(investigation.id)):return pair
                resolution['investigation']=pair[0]
                if investigation.status=='done':parent=pair[0]
            probe=dict(version=1,kind='diagnostic',stage=stage,release=body['release'],
                source=facts['source'],source_run=facts['source_run'],block_event=facts['block_event'],cause=facts['cause'],
                inputs={'incident':data['incident']},escalated_from=pair[-1] if pair else task.id,hold_resolution=resolution)
            key=digest([self.project.fingerprint(),data['incident'],protocol,role])
            prior=conn.execute('SELECT id,body FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
            if prior:
                previous=json.loads(prior['body'])
                if review_followup and previous!=probe:
                    # One incident gets one decision activity. A later hold is
                    # retained history, not authority to rewrite or duplicate it.
                    old_key=previous.get('hold_resolution',{}).get('diagnosis')
                    old=self.store.receipt(old_key,kind='diagnostic_decision')
                    expected={**probe,'escalated_from':previous.get('escalated_from'),
                        'hold_resolution':{**probe['hold_resolution'],'diagnosis':old_key}}
                    if (previous!=expected or old['payload'].get('incident')!=data['incident']
                            or old['payload'].get('action')!='hold'
                            or old['payload'].get('project')!=self.project.fingerprint()
                            or old['binding'].get('task')!=previous.get('escalated_from')
                            or old['binding'].get('actor')!=self.project.technical_roles['cto']
                            or old['binding'].get('release')!=body['release']
                            or old['binding'].get('kind')!='diagnostic'
                            or old['binding'].get('reviewing') is not False):
                        raise ValueError('resolution handoff identity drift')
                elif previous!=probe:raise ValueError('resolution handoff identity drift')
                pair.append(prior['id']);continue
            if self.board.guard:self.board.guard()
            pair.append(kb.create_task(conn,title=('INVESTIGATE ' if role=='investigate' else 'DECIDE ')+source.title,
                body=json.dumps(probe),assignee=self.project.technical_roles[stage],parents=[parent],
                priority=100,workspace_kind='dir',workspace_path=str(self.store.tree(facts['snapshot'])),
                completion_contract='local-only',max_retries=0,max_runtime_seconds=600,idempotency_key=key))
        return pair

    def create(self,conn,incident,stage,*,previous=None):
        kb,_,_=native();record=self.store.receipt(incident,kind='incident');data=record['payload']
        if data['project']!=self.project.fingerprint():raise ValueError('diagnostic incident belongs to another project')
        actor=self.project.technical_roles[stage]
        body=dict(version=1,kind='diagnostic',release=record['binding']['release'],stage=stage,
            source=data['source'],source_run=data['source_run'],block_event=data['block_event'],
            cause=data['cause'],inputs={'incident':incident},escalated_from=previous)
        if previous:
            parent=kb.get_task(conn,previous);prior=json.loads(parent.body) if parent else {}
            failed=kb.latest_run(conn,previous) if parent and parent.status in ('blocked','triage') else None
            failed_lead=(stage=='cto' and prior.get('stage')=='lead' and failed is not None
                         and failed.ended_at is not None and failed.outcome in ('blocked','failed','timed_out'))
            if (not parent or (parent.status!='done' and not failed_lead) or prior.get('kind')!='diagnostic' or prior.get('version')!=1
                    or prior.get('inputs',{}).get('incident')!=incident or prior.get('release')!=body['release']
                    or prior.get('stage') not in self.project.technical_roles or prior['stage']==stage
                    or parent.assignee!=self.project.technical_roles[prior['stage']]):
                raise ValueError('completed scoped predecessor diagnosis required')
        legacy=digest([self.project.fingerprint(),data['source'],data['source_run'],data['block_event'],'diagnostic',stage])
        row=conn.execute('SELECT id FROM tasks WHERE idempotency_key=?',(legacy,)).fetchone()
        if row:
            existing=json.loads(kb.get_task(conn,row['id']).body)
            if existing==body:return row['id']
            if not previous or {**existing,'escalated_from':previous}!=body:
                raise ValueError('diagnostic anchor contract drift')
        key=digest([legacy,'predecessor',previous]) if previous else legacy
        row=conn.execute('SELECT id FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if row:
            if json.loads(kb.get_task(conn,row['id']).body)!=body:raise ValueError('diagnostic successor contract drift')
            return row['id']
        return kb.create_task(conn,title='DIAG '+stage+' — '+data['source'],assignee=actor,priority=100,
            body=json.dumps(body),
            workspace_kind='dir',workspace_path=str(self.store.tree(data['snapshot'])),completion_contract='local-only',
            max_retries=2,max_runtime_seconds=600,idempotency_key=key)

    def discover(self,conn,task,settle):
        kb,_,_=native();body=json.loads(task.body)
        if body.get('kind')=='diagnostic':
            if body.get('hold_resolution'):return
            if body['stage']=='lead':self.create(conn,body['inputs']['incident'],'cto',previous=task.id)
            return
        if body.get('version')!=1 or body.get('kind') not in ('brief','plan','tests','implementation','integration'):return
        row=conn.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task.id,)).fetchone()
        event=conn.execute("SELECT * FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up','block_loop_detected') ORDER BY id DESC LIMIT 1",(task.id,)).fetchone()
        if not row or not row['ended_at'] or not event:return
        claimed=conn.execute("SELECT payload FROM task_events WHERE run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        reviewing=bool(claimed and json.loads(claimed[0]).get('source_status')=='review')
        stage='cto' if task.status=='triage' else self.stage_for(reviewing,row['profile'])
        key=digest([self.project.fingerprint(),task.id,row['id'],event['id'],'diagnostic',stage])
        existing=conn.execute('SELECT id FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:return
        for candidate in self.cards(conn):
            anchor=json.loads(candidate.body or '{}')
            if (anchor.get('kind')=='diagnostic' and anchor.get('version')==1 and anchor.get('release')==body['release']
                    and anchor.get('source')==task.id and anchor.get('source_run')==row['id']
                    and anchor.get('block_event')==event['id'] and anchor.get('stage')==stage):return
        settle(task.id,conn=conn)
        author=row['profile'];origin,handoff=self.handoff(conn,task)
        if reviewing:
            author=origin['implementer']
        source=Run(task.id,row['id'],row['profile'],body['kind'],reviewing,author,body['release'],digest(body))
        snapshot=self.snapshot(conn,task,source,handoff)
        failure=row['summary'] or row['error'] or task.result or 'Native worker could not complete'
        payload=json.loads(event['payload'] or '{}')
        reason=payload.get('reason');escalation_id=None;control_refusal=None;suite_refusal=None;browser_refusal=None;submission_refusal=None
        if isinstance(reason,str):
            try:data=json.loads(reason)
            except (ValueError,TypeError):data=None
            if isinstance(data,dict):
                if data.get('failure'):
                    failure_record=self.store.receipt(data['failure'],kind='worker_failure')
                    if failure_record['binding']==source.binding():
                        failure=failure_record['payload']['message']
                        submission_refusal=failure_record['payload'].get('submission_refusal')
                        if submission_refusal:submission_refusal_context(self.store,self.project,source.binding(),submission_refusal,snapshot)
                        control_refusal=failure_record['payload'].get('control_refusal')
                        if control_refusal:control_refusal_context(self.store,self.project,source.binding(),control_refusal,snapshot)
                        suite_refusal=failure_record['payload'].get('suite_refusal')
                        if suite_refusal:
                            facts=suite_refusal_context(self.store,self.project,source.binding(),suite_refusal,snapshot)
                            if facts.get('infrastructure_error'):
                                failure='Validation job failed: '+facts['infrastructure_error']+'; receipt '+suite_refusal+'; activity: '+failure
                        browser_refusal=failure_record['payload'].get('browser_refusal')
                        if browser_refusal:browser_refusal_context(self.store,self.project,source.binding(),browser_refusal)
                if data.get('category')=='review_escalation':
                    record=self.store.receipt(data['escalation'],kind='review_escalation')
                    review=self.store.receipt(record['payload']['review'],kind='test_review' if source.kind=='tests' else 'delivery_review')
                    if (not source.reviewing or record['binding']!=source.binding()
                            or record['payload']['project']!=self.project.fingerprint()
                            or record['payload']['snapshot']!=snapshot or review['binding']!=source.binding()
                            or review['payload']['project']!=self.project.fingerprint()
                            or review['payload']['snapshot']!=snapshot or review['payload']['verdict']['decision']!='changes'):
                        raise ValueError('exact review escalation required')
                    escalation_id=data['escalation']
                    failure='Independent review technical impasse; CTO experiment and guidance required'
        cause=digest([task.id,source.contract,reviewing,snapshot,failure])
        effects=self.expired_effects(task.id)
        allowed=task.status=='blocked' and not effects
        category=('native_triage' if task.status=='triage' else 'controller_effect' if effects else
                  'technical_impasse' if escalation_id else 'document_activity' if source.kind in ('brief','plan') else
                  'integration_activity' if source.kind=='integration' else 'quality_gate' if control_refusal or suite_refusal else 'worker_activity')
        incident=self.store.record('incident',source.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot,
            source=task.id,source_run=row['id'],block_event=event['id'],cause=cause,failure=failure,category=category,
            source_state=task.status,resume_allowed=allowed,controller_effects=effects,
            **({'reassessment_review':body['inputs']['reassessment_review']} if source.reviewing and body.get('inputs',{}).get('reassessment_review') else {}),
            recovery_limit=None if allowed else 'Native triage or expired controller effect requires a scoped technical repair; preserve phase and breaker, never repeat the mutation.',
            **({'document_kind':source.kind} if source.kind in ('brief','plan') else {}),
            **({'control_refusal':control_refusal} if control_refusal else {}),
            **({'suite_refusal':suite_refusal} if suite_refusal else {}),
            **({'submission_refusal':submission_refusal} if submission_refusal else {}),
            **({'browser_refusal':browser_refusal} if browser_refusal else {}),
            workspace=task.workspace_path,**({'review_escalation':escalation_id} if escalation_id else {})))
        # A native idempotent anchor survives restart before stage materialization.
        self.create(conn,incident,stage)

    def apply(self,conn,task):
        kb,_,_=native();body=json.loads(task.body);row=kb.latest_run(conn,task.id)
        if not row or row.outcome!='completed' or not row.metadata or 'diagnosis' not in row.metadata:return
        receipt_id=row.metadata['diagnosis'];receipt=self.store.receipt(receipt_id,kind='diagnostic_decision');data=receipt['payload']
        expected=Run(task.id,row.id,task.assignee,'diagnostic',False,task.assignee,body['release'],digest(body))
        if (receipt['binding']!=expected.binding() or data['project']!=self.project.fingerprint()
                or data['incident']!=body['inputs']['incident']
                or task.assignee!=self.project.technical_roles[body['stage']]):raise ValueError('exact native diagnostic evidence required')
        incident=self.store.receipt(data['incident'],kind='incident');source=incident['payload']
        if body.get('hold_resolution',{}).get('role')=='investigate':
            if data['action']!='hold':raise ValueError('investigation records findings only; CTO decides')
            return
        if data['action']=='escalate':
            if body['stage']!='lead':raise ValueError('only lead escalates to CTO')
            self.create(conn,data['incident'],'cto',previous=task.id);return
        if data['action']=='hold' and source.get('review_escalation') and not body.get('hold_resolution'):
            target=kb.get_task(conn,source['source']);current=kb.latest_run(conn,target.id) if target else None
            if current and current.id!=source['source_run']:return  # Historical decision; never reapply to new work.
            self.coordinate_hold(conn,task,receipt_id)
            return
        if data['action']=='return_author':
            self.return_author(conn,task,receipt_id,receipt,incident)
            return
        if data['action'] in ('hold','repair_tests'):
            # Keep the hold receipt/source block, but do not strand a technical
            # impediment at Lead. CTO is the final technical decision owner.
            if data['action']=='repair_tests' and body['stage']!='cto':raise ValueError('only CTO may authorize technical test repair')
            if body['stage']=='lead':self.create(conn,data['incident'],'cto',previous=task.id)
            return
        if source.get('resume_allowed') is False:raise EffectBlocked('native triage/controller effect needs scoped repair; preserve source')
        experiment=self.store.receipt(data['experiment'],kind='diagnostic_experiment')
        if experiment['binding']!=expected.binding() or experiment['payload']['incident']!=data['incident']:
            raise ValueError('resume requires its current validated experiment')
        identity=dict(diagnosis=receipt_id,source=source['source'],block_event=source['block_event'])
        key=digest(identity)
        path=self.journal.root/(digest(key+':resume')+'.json')
        if path.exists() and json.loads(path.read_bytes())['state']=='done':return
        attempts=0
        for other in self.cards(conn):
            previous=json.loads(other.body or '{}')
            if previous.get('kind')!='diagnostic' or previous.get('cause')!=source['cause']:continue
            prior=kb.latest_run(conn,other.id)
            if not prior or not prior.metadata or not prior.metadata.get('diagnosis'):continue
            old_id=prior.metadata['diagnosis'];old=self.store.receipt(old_id,kind='diagnostic_decision')['payload']
            old_incident=self.store.receipt(old['incident'],kind='incident')['payload']
            old_key=digest(dict(diagnosis=old_id,source=old_incident['source'],block_event=old_incident['block_event']))
            old_path=self.journal.root/(digest(old_key+':resume')+'.json')
            if old_path.exists() and json.loads(old_path.read_bytes())['state']=='done':attempts+=1
        if attempts>=2:raise EffectBlocked('two recoveries without changed evidence; require new diagnosis or changed preconditions')
        def fresh():
            target=kb.get_task(conn,source['source'])
            latest=kb.latest_run(conn,target.id)
            event=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up') ORDER BY id DESC LIMIT 1",(target.id,)).fetchone()
            if (target.status!='blocked' or not latest or latest.id!=source['source_run'] or not event or event[0]!=source['block_event']
                    or target.assignee!=incident['binding']['actor']
                    or target.workspace_path!=source['workspace']
                    or digest(json.loads(target.body))!=incident['binding']['contract']):
                raise EffectBlocked('diagnosis is stale for the current source impediment')
            if self.expired_effects(target.id):raise EffectBlocked('controller effect expired during diagnosis; preserve its identity')
            if (incident['binding']['kind'] in ('tests','implementation') and not incident['binding']['reviewing']
                    and self.store.capture(Path(target.workspace_path))!=source['snapshot']):
                raise EffectBlocked('source workspace changed after the diagnostic snapshot')
        # Full guidance is resolved from the receipt. Copying model prose here
        # can turn an incidental PR URL into a native duplicate-work guard.
        guidance='DIAG '+receipt_id
        def comment_observed():
            row=conn.execute('SELECT id FROM task_comments WHERE task_id=? AND author=? AND body=?',
                (source['source'],task.assignee,guidance)).fetchone()
            return {'comment':row[0]} if row else None
        def comment():
            fresh();return {'comment':kb.add_comment(conn,source['source'],task.assignee,guidance)}
        self.journal.do(key+':guidance',identity,comment,comment_observed)
        def resumed():
            row=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind='unblocked' AND id>? ORDER BY id LIMIT 1",
                (source['source'],source['block_event'])).fetchone()
            return {'event':row[0]} if row and comment_observed() else None
        def resume():
            fresh()
            if not kb.unblock_task(conn,source['source']):raise EffectBlocked('native resume refused')
            return resumed()
        self.journal.do(key+':resume',identity,resume,resumed)

    def return_author(self,conn,task,key,decision,incident):
        """Atomic native review reopen; no synthetic reviewer run or delivery approval."""
        kb,_,_=native();facts=incident['payload'];scope=incident['binding']
        if (not scope['reviewing'] or not facts.get('review_escalation')
                or decision['binding']['actor']!=self.project.technical_roles['cto']):
            raise ValueError('exact independent review and CTO return authority required')
        escalation=self.store.receipt(facts['review_escalation'],kind='review_escalation')
        review=self.store.receipt(escalation['payload']['review'],kind='test_review' if scope['kind']=='tests' else 'delivery_review')
        experiment=self.store.receipt(decision['payload']['experiment'],kind='diagnostic_experiment')
        if (escalation['binding']!=scope or review['binding']!=scope or review['payload']['snapshot']!=facts['snapshot']
                or review['payload']['verdict']['decision']!='changes' or scope['actor']==scope['author']
                or experiment['binding']!=decision['binding'] or experiment['payload']['incident']!=decision['payload']['incident']):
            raise ValueError('exact rejected snapshot and current CTO evidence required')
        comment='DIAG '+key
        with kb.write_txn(conn):
            if conn.execute("SELECT 1 FROM task_comments WHERE task_id=? AND author=? AND body=?",(facts['source'],task.assignee,comment)).fetchone():return
            target=kb.get_task(conn,facts['source']);latest=kb.latest_run(conn,target.id)
            if (target.status!='blocked' or not latest or latest.id!=facts['source_run'] or not latest.ended_at
                    or target.assignee!=scope['actor'] or digest(json.loads(target.body))!=scope['contract']
                    or self.expired_effects(target.id)):
                raise EffectBlocked('review return source changed or still active')
            handoff,_=self.handoff(conn,target)
            if handoff.get('implementer')!=scope['author']:raise ValueError('original author provenance changed')
            # Same parent gating/event as native review reopen, composed atomically
            # from blocked review. Preserve all failure and recurrence counters.
            if self.board.guard:self.board.guard()
            status=kb._landing_status_after_parents(conn,target.id)
            changed=conn.execute("UPDATE tasks SET status=?, assignee=?, current_run_id=NULL, claim_lock=NULL, claim_expires=NULL, worker_pid=NULL, worker_started_at=NULL WHERE id=? AND status='blocked'",(status,scope['author'],target.id))
            if changed.rowcount!=1:raise EffectBlocked('author return refused')
            kb._append_event(conn,target.id,'review_reopened',dict(status=status,implementer=scope['author'],diagnosis=key,review=escalation['payload']['review']))
            kb.add_comment(conn,target.id,task.assignee,comment)

    def reconcile(self,conn,settle):
        if not self.project.technical_roles:return {}
        issues={}
        for task in self.cards(conn):
            try:
                body=json.loads(task.body or '{}')
                if body.get('kind')=='diagnostic' and task.status=='done':self.apply(conn,task)
                elif task.status in ('blocked','triage'):self.discover(conn,task,settle)
            except (ValueError,KeyError,TypeError,EffectBlocked,Pending,OSError) as error:
                issues[task.id]=dict(category=type(error).__name__,owner=self.project.technical_roles['cto'],
                    detail=str(error)[:500],next_action='Observe the recorded identity/effect and repair preconditions; never reset or resubmit blindly.')
        return issues

    def status(self,conn):
        if not self.project.technical_roles:return []
        kb,_,_=native();incidents={};tasks=self.cards(conn);ranks={}
        bodies={task.id:json.loads(task.body or '{}') for task in tasks}
        def depth(task_id,seen=frozenset()):
            if task_id in seen:raise ValueError('diagnostic predecessor cycle')
            body=bodies[task_id];parent=body.get('escalated_from')
            if not parent:return 0
            prior=bodies.get(parent,{})
            if prior.get('kind')!='diagnostic' or prior.get('inputs',{}).get('incident')!=body['inputs']['incident']:
                raise ValueError('diagnostic predecessor scope changed')
            return 1+depth(parent,seen|{task_id})
        for task in tasks:
            body=json.loads(task.body or '{}')
            if body.get('kind')!='diagnostic':continue
            key=body['inputs']['incident'];record=self.store.receipt(key,kind='incident')
            target=kb.get_task(conn,body['source']);state='blocked'
            if target.status in ('ready','running','review'):state='revalidating'
            if target.status in ('blocked','triage'):
                latest=kb.latest_run(conn,target.id)
                if latest and latest.id!=record['payload']['source_run']:state='revalidation_failed'
            if target.status=='done':
                last=kb.latest_run(conn,target.id);metadata=last.metadata if last else {}
                kind=record['binding']['kind']
                name,evidence_kind={'tests':('tests','tests_frozen'),'implementation':('delivery','delivery_review'),
                    'integration':('release_evidence','release_evidence'),'plan':('plan_review','plan_review'),
                    'brief':('approved_brief','brief_approval')}[kind]
                state='evidence_missing'
                if metadata and metadata.get(name):
                    evidence=self.store.receipt(metadata[name],kind=evidence_kind)
                    if kind=='brief':
                        from .intake import Intake
                        approval,proposal=Intake(self.project,self.store,self.board).approved(metadata[name])
                        valid=(approval['binding']['task']==target.id and proposal['binding']['contract']==record['binding']['contract'])
                    else:
                        reviewed,_,_=self.board.closed_review(target.id)
                        valid=(evidence['binding']==reviewed.binding() and reviewed.contract==record['binding']['contract'])
                    if valid and evidence['payload']['project']==self.project.fingerprint():state='resolved'
            row=kb.latest_run(conn,task.id);decision=None
            if row and isinstance(row.metadata,dict) and row.metadata.get('diagnosis'):
                decision=self.store.receipt(row.metadata['diagnosis'],kind='diagnostic_decision')['payload']
                if decision['incident']!=key:raise ValueError('diagnostic outcome belongs to another incident')
                if decision['action']=='hold' and state!='resolved':state='held'
            if task.status in ('blocked','triage') and state!='resolved':state='diagnosis_failed'
            rank=(depth(task.id),int(body['stage']=='cto'))
            if key in ranks and ranks[key]>rank:continue
            ranks[key]=rank
            incidents[key]=dict(source=target.id,diagnostic=task.id,stage=body['stage'],state=state,
                category=record['payload'].get('category','worker_activity'),
                source_run=record['payload']['source_run'],block_event=record['payload']['block_event'],
                owner=target.assignee if state=='revalidating' else task.assignee,
                resume_allowed=record['payload'].get('resume_allowed',True),
                next_action=(decision.get('next_step',decision['verdict']) if decision else
                    'CTO diagnostic failed: inspect its retained run and repair protocol/capability before another attempt.' if state=='diagnosis_failed' else
                    'Assigned technical diagnosis; inspect recorded failure and execute a permitted experiment.'),
                delivery_approval=False)
            for candidate in tasks:
                correction=json.loads(candidate.body or '{}')
                if correction.get('repair_of')!=target.id:continue
                context=self.store.receipt(correction['repair_context'],kind='repair_context')
                if context['payload']['source']!=target.id or context['payload']['project']!=self.project.fingerprint():
                    raise ValueError('corrective incident link changed')
                current=incidents[key]
                current.update(state='correction_blocked' if candidate.status in ('blocked','triage') else 'repairing',
                    corrective_task=candidate.id,owner=candidate.assignee,
                    next_action='Follow corrective card '+candidate.id+' and its reviewed package; the original failure remains preserved.')
                anchor=kb.get_task(conn,correction['anchor'])
                from .intake import Intake
                if Intake(self.project,self.store,self.board).terminal(anchor):current.update(state='resolved_by_repair',next_action='Release homologated with corrective evidence; original failed execution remains historical.')
        return list(incidents.values())


def register_diagnostic(sandbox,quality,on_terminal):
    from tools.registry import registry
    operations=Diagnostic(sandbox,quality)
    finding=dict(type='object',additionalProperties=False,required=['path','line','detail'],properties=dict(
        path={'type':'string'},line={'type':'integer','minimum':1},detail={'type':'string','minLength':1,'maxLength':2000}))
    reference=dict(type='object',additionalProperties=False,required=['evidence','detail'],properties=dict(
        evidence=dict(type='string',pattern=r'^(incident|experiment|[a-f0-9]{64})$',description='incident, current experiment, or exact retained diagnostic experiment receipt from diagnostic_report; citation grants no transition authority'),detail=dict(type='string',minLength=1,maxLength=2000)))
    schemas=dict(diagnostic_validate=dict(type='object',additionalProperties=False,required=['hypothesis'],properties=dict(
        hypothesis={'type':'string','minLength':1,'maxLength':2000},replacements=dict(type='object',minProperties=1,maxProperties=16,
            additionalProperties={'type':'string','maxLength':131072}))),
        diagnostic_decide=dict(type='object',additionalProperties=False,required=['action','reason','findings'],properties=dict(
            action={'type':'string','enum':operations.actions()},reason={'type':'string','minLength':1,'maxLength':2000},
            findings=dict(type='array',minItems=1,maxItems=8,items={'oneOf':[finding,reference]}))))
    if 'return_author' in operations.actions():
        schemas['diagnostic_decide']['properties']['verification']=dict(type='object',additionalProperties=False,
            required=['reachable_scenario','negative_control'],properties={k:dict(type='string',minLength=1,maxLength=2000) for k in ('reachable_scenario','negative_control')})
    if 'repair_tests' in operations.actions():
        schemas['diagnostic_decide']['properties']['repair_scope']=dict(
            type='object',additionalProperties=False,required=['test_paths','cases'],
            properties=dict(test_paths=dict(type='array',minItems=1,maxItems=20,items=dict(type='string')),
                            cases=dict(type='array',minItems=1,maxItems=20,items=dict(type='string')),
                            mode=dict(type='string',enum=['strengthen']),
                            product_imports=dict(type='array',minItems=1,maxItems=4,items=dict(type='string'))))
    if getattr(operations,'resolution',{}):
        schemas['diagnostic_decide']['properties']['next_step']=dict(type='object',additionalProperties=False,
            description='Required for hold: exact technical responsibility and next verifiable operation; not approval.',
            required=['owner','operation','expected_evidence','precondition'],properties=dict(
                owner=dict(type='string',enum=list(quality.project.technical_roles.values())),
                **{key:dict(type='string',minLength=1,maxLength=1200) for key in ('operation','expected_evidence','precondition')}))
    if getattr(operations,'resolution',{}).get('protocol')=='executable-decision-1':
        schemas['diagnostic_decide']['required'].append('ruling')
        schemas['diagnostic_decide']['properties']['ruling']=dict(type='object',additionalProperties=False,
            required=['choice','correction','remaining','blocker'],properties=dict(
                **{k:dict(type='string',minLength=1,maxLength=2000) for k in ('choice','correction','remaining')},
                blocker=dict(type='string',enum=['none','infrastructure','missing_evidence','tool_capability'])))
    if operations.incident.get('document_kind'):
        properties=schemas['diagnostic_validate']['properties'];properties.pop('replacements')
        properties['document']=dict(type='object',description='Optional proposed brief/plan for the fixed validator. Never writes the source. Omit to validate document.json from the incident.')
    schemas['diagnostic_report']=dict(type='object',additionalProperties=False,required=['offset'],properties=dict(offset=dict(type='integer',minimum=0),experiment=dict(type='string',pattern='^[a-f0-9]{64}$',description='Optional retained diagnostic experiment from the same incident; read-only, never approval.'),implementation_path=dict(type='string',description='Read an authorized preserved root Python product file instead of an experiment report. Offset is a character offset; not a workspace path or caller-selected snapshot.')))
    failures={}
    def handler(method,terminal):
        def invoke(args,**kwargs):
            identity=digest([method.__name__,args])
            if failures.get(identity,0)>=2:
                raise ValueError('identical diagnostic operation already rejected twice; inspect the returned error and supplied diagnostic context, change the unsupported proposal or record hold; no operation was repeated')
            try:result=method(args)
            except (ValueError,EffectBlocked):
                failures[identity]=failures.get(identity,0)+1
                raise
            if terminal and on_terminal:on_terminal(result)
            return json.dumps(result)
        return invoke
    for name,method in (('diagnostic_validate',operations.validate),('diagnostic_decide',operations.decide),('diagnostic_report',operations.report_page)):
        registry.register(name=name,toolset='fabriquinha_delivery',schema=dict(name=name,parameters=schemas[name],
            description='Technical diagnosis only. Read immutable evidence, run a fixed disposable SPIKE, propose guidance or escalate. '
                'Cite a real source line, evidence=incident/current experiment, or the exact retained experiment receipt returned by diagnostic_report. Historical citation does not authorize resume or test repair; those still require a current experiment. Never invent a product defect. '
                'Never edit the author, weaken tests, approve delivery or send technical decisions to the CEO.'),
            handler=handler(method,name=='diagnostic_decide'))
    return set(schemas),operations
