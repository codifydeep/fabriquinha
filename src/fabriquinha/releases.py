"""Materialize a reviewed DAG and accept its evidence; Hermes owns all states."""
import json
from pathlib import Path
import time
import re
import subprocess
from .artifacts import digest, identity
from .effects import Journal, Pending, EffectBlocked, write_json
from .intake import plan
from .kanban_lane import native
from .publication import Publication
from .deployment import Deployment
from .config import execution_context
from .browser import load_contract,author_protocol
from .quality import Quality, CONTROL_CONTRACT
from .executor import validation_files


def ordered(tasks):
    remaining={item['id']:item for item in tasks};result=[];done=set()
    if len(remaining)!=len(tasks):raise ValueError('unique package IDs required')
    while remaining:
        ready=[key for key,item in remaining.items() if set(item['depends_on'])<=done]
        if not ready:raise ValueError('known acyclic package dependencies required')
        for key in ready:result.append(remaining.pop(key));done.add(key)
    return result


def continuation_context(continuation):
    """Reviewed origin is provenance, not a second task for the implementer.

    The caller has verified the full immutable proposal/review. Current brief,
    architecture, package acceptance and frozen controls are supplied separately.
    Keep exact historical references and the submission contract, not old failure
    prose that can be mistaken for unfinished work on a dependent package.
    """
    return dict(review=continuation['review'],context=continuation['context_id'],
        task=continuation['task'],source=continuation['context']['source'],
        contract=continuation['context']['submission_contract'],delivery_approval=False)


class Releases:
    def __init__(self,project,store,board,intake):
        self.project,self.store,self.board,self.intake=project,store,board,intake
        self.journal=Journal(store.root/'effects')

    @staticmethod
    def binding(anchor):
        body=json.loads(anchor.body)
        return dict(actor='controller',task=anchor.id,release=body['release'],contract=digest(body))

    def folder(self,anchor):return self.store.root/'releases'/identity(json.loads(anchor.body)['release'])

    def body(self,kind,release,anchor,review,package,inputs):
        return dict(version=1,kind=kind,release=release,release_anchor=anchor,release_plan=review,
            package=package['id'],criteria=package['criteria'],acceptance=package['acceptance'],inputs=inputs)

    def closed(self,task,key,kind):
        run,metadata,handoff=self.board.closed_review(task)
        receipt_id=metadata.get(key);record=self.store.receipt(receipt_id,kind=kind)
        if record['binding']!=run.binding() or record['payload']['project']!=self.project.fingerprint():
            raise ValueError('completed receipt must match exact native run and project')
        return receipt_id,record,handoff

    def specification(self,conn,anchor):
        kb,_,_=native();release=json.loads(anchor.body)['release']
        row=conn.execute('SELECT id FROM tasks WHERE idempotency_key=? AND status!=?',(digest([release,'plan']),'archived')).fetchone()
        task=kb.get_task(conn,row['id']) if row else None
        if not task or task.status!='done':return None
        review_id,review,handoff=self.closed(task.id,'plan_review','plan_review')
        body=json.loads(task.body);approval=body['inputs']['approved_brief']
        business,brief=self.intake.approved(approval)
        proposed=self.store.receipt(review['payload']['plan'],kind='work_plan')
        if (review['payload']['verdict']['decision']!='approve' or handoff.get('plan')!=review['payload']['plan']
                or review['binding']['release']!=release or review['binding']['author']!=self.project.coordination_roles['lead']
                or proposed['binding']['task']!=task.id or proposed['binding']['contract']!=digest(body)
                or proposed['binding']['actor']!=review['binding']['author'] or proposed['binding']['release']!=release
                or proposed['payload']['project']!=self.project.fingerprint() or proposed['payload']['approval']!=approval
                or business['binding']['release']!=release):raise ValueError('exact approved plan and business scope required')
        document=plan(proposed['payload']['document'],brief['payload']['document'],self.project)
        return dict(task=task.id,review=review_id,approval=approval,brief=brief['payload']['document'],document=document)

    def seed(self,anchor,specification,services):
        path=self.folder(anchor)/'seed.json'
        expected=dict(project=self.project.fingerprint(),plan_review=specification['review'])
        if not path.exists():
            repository,_=services(self.project.delivery_roles['integration'])
            base=repository.base();snapshot=repository.snapshot(base)
            write_json(path,{**expected,'commit':base,'snapshot':snapshot})
        value=json.loads(path.read_bytes())
        if any(value.get(key)!=item for key,item in expected.items()):raise ValueError('release seed scope drift')
        self.store.tree(value['snapshot'])
        return self.store.record('release_seed',self.binding(anchor),value)

    def materialize(self,conn,anchor,specification,services,*,path=None,seed=None):
        kb,_,_=native();path=path or self.folder(anchor)/'graph.json';binding=self.binding(anchor)
        bundle=validation_files(self.project,self.store)[0]
        if path.exists():
            graph_id=json.loads(path.read_bytes())['receipt'];record=self.store.receipt(graph_id,kind='release_graph')
            graph=record['payload']
            if (record['binding']!=binding or graph['project']!=self.project.fingerprint() or graph['plan_review']!=specification['review']
                    or graph.get('validation_bundle')!=bundle):
                raise ValueError('release graph or approved plan changed')
        else:
            seed=seed or self.seed(anchor,specification,services);baseline=self.store.receipt(seed,kind='release_seed')['payload']
            previous=None;by_package={};items=[]
            for package in ordered(specification['document']['tasks']):
                self.project.reviewer(package['owner'],exclude=(self.project.delivery_roles['tests'],))
                parents=[specification['task'],*[by_package[key] for key in package['depends_on']]]
                if previous and previous not in parents:parents.append(previous)
                test_inputs={'baseline':'parent:'+previous+':baseline' if previous else baseline['snapshot'],
                    'base_commit':'parent:'+previous+':base_commit' if previous else baseline['commit']}
                cards={}
                for phase in ('tests','implementation','integration'):
                    owner=(package['owner'] if phase=='implementation' else self.project.delivery_roles[phase])
                    inputs=(test_inputs if phase=='tests' else {'tests':'parent:'+cards['tests']['id']+':tests'}
                            if phase=='implementation' else {'delivery':'parent:'+cards['implementation']['id']+':delivery'})
                    if specification.get('repair'):inputs={**inputs,'repair_review':specification['repair']['review']}
                    deps=parents if phase=='tests' else [cards['tests' if phase=='implementation' else 'implementation']['id']]
                    body=self.body(phase,binding['release'],anchor.id,specification['review'],package,inputs)
                    if specification.get('repair'):body['repair_plan']=specification['repair']['plan']
                    workspace=self.store.root.parent/'work'/binding['release']/package['id']/phase
                    workspace.mkdir(mode=0o777,parents=True,exist_ok=True);workspace.chmod(0o777)
                    contract=self.project.repository.removeprefix('https://github.com/') if phase=='integration' else 'local-only'
                    task=kb.create_task(conn,title=phase.upper()+' '+package['title'],body=json.dumps(body),assignee=owner,
                        parents=deps,workspace_kind='dir',workspace_path=str(workspace),completion_contract=contract,
                        initial_status='blocked',max_retries=2,max_runtime_seconds=600,
                        idempotency_key=digest([binding['release'],specification['review'],package['id'],phase]))
                    cards[phase]=dict(id=task,body=body,parents=deps,workspace=str(workspace),owner=owner,completion_contract=contract)
                previous=cards['integration']['id'];by_package[package['id']]=previous
                items.append(dict(package=package,cards=cards))
            graph=dict(project=self.project.fingerprint(),plan_review=specification['review'],seed=seed,items=items,
                serialized_integrations=True,qualification=self.project.qualification,
                **({'validation_bundle':bundle} if bundle else {}))
            graph_id=self.store.record('release_graph',binding,graph);write_json(path,{'receipt':graph_id})
        # Every card starts parked. Publish the whole immutable graph before
        # activating any card, so a crash cannot dispatch half-built dependencies.
        for item in graph['items']:
            for card in item['cards'].values():
                self.check_card(conn,card)
                task=kb.get_task(conn,card['id'])
                if task.status=='blocked' and kb.latest_run(conn,task.id) is None:
                    if self.board.guard:self.board.guard()
                    if not kb.unblock_task(conn,task.id):raise ValueError('native initial graph activation refused')
        return graph_id,graph

    def graph_path(self,anchor,body):
        repair=body.get('repair_plan')
        continuation=body.get('continuation_plan')
        if continuation is not None:
            if repair is not None or not re.fullmatch(r't_[a-f0-9]{8}',continuation):raise ValueError('one native continuation plan required')
            return self.folder(anchor)/('continuation-'+continuation+'.json')
        if repair is not None and not re.fullmatch(r't_[a-f0-9]{8}',repair):raise ValueError('native corrective plan identity required')
        return self.folder(anchor)/(('repair-'+repair+'.json') if repair else 'graph.json')

    def upgrade_unvalidated_graphs(self,conn,upgrade):
        """Version graph pins during fenced operator maintenance; keep all cards."""
        authority=self.store.receipt(upgrade,kind='acceptance_upgrade')
        data=authority['payload'];old=data['before']['validation_bundle'];new=data['after']['validation_bundle']
        if authority['binding']!={'project':self.project.fingerprint(),'actor':'operator'}:
            raise ValueError('operator bundle transition required')
        kb,_,_=native();changed=[]
        for path in sorted((self.store.root/'releases').glob('*/graph.json')):
            key=json.loads(path.read_bytes())['receipt'];record=self.store.receipt(key,kind='release_graph')
            anchor=kb.get_task(conn,record['binding']['task'])
            if not anchor or anchor.status!='blocked' or path!=self.graph_path(anchor,{}):
                raise ValueError('active original graph required for pre-quality transition')
            specification=self.specification(conn,anchor);graph=record['payload']
            if (not specification or record['binding']!=self.binding(anchor)
                    or graph['project']!=self.project.fingerprint() or graph['plan_review']!=specification['review']
                    or graph.get('validation_bundle') not in (old,new)):
                raise ValueError('exact approved graph and previous validator required')
            for item in graph['items']:
                for card in item['cards'].values():self.check_card(conn,card)
            if graph['validation_bundle']==new:continue
            successor=self.store.record('release_graph',record['binding'],
                {**graph,'validation_bundle':new,'previous_graph':key,'validation_upgrade':upgrade})
            if json.loads(path.read_bytes())!={'receipt':key}:raise ValueError('graph pointer changed during maintenance')
            write_json(path,{'receipt':successor});changed.append(dict(before=key,after=successor))
        return changed

    def check_card(self,conn,card):
        kb,_,_=native();task=kb.get_task(conn,card['id'])
        parents={row[0] for row in conn.execute('SELECT parent_id FROM task_links WHERE child_id=?',(card['id'],))}
        if (not task or json.loads(task.body)!=card['body'] or task.workspace_kind!='dir' or task.workspace_path!=card['workspace']
                or (task.completion_contract!=card['completion_contract'] and not self.bound_contract(conn,task))
                or parents!=set(card['parents'])):
            raise ValueError('materialized contract/dependencies/workspace changed; preserve work')
        allowed={card['owner'],*self.project.reviewers_for(card['owner'])}
        if task.assignee not in allowed:raise ValueError('materialized card owner changed')
        return task

    def bound_contract(self,conn,task):
        """Native acceptance binds repo -> exact PR once; never a green sibling."""
        body=json.loads(task.body)
        if body.get('kind')!='integration' or not re.fullmatch(re.escape(self.project.repository)+r'/pull/[1-9][0-9]*',task.completion_contract or ''):
            return False
        row=conn.execute("SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(task.id,)).fetchone()
        handoff=json.loads(row['metadata'] or '{}') if row else {}
        if handoff.get('published_pr')!=task.completion_contract:return False
        rollout=self.store.receipt(handoff['rollout'],kind='rollout')['payload']
        artifact=self.store.receipt(rollout['candidate'],kind='artifact')['payload']
        integrated=self.store.receipt(artifact['integrated'],kind='integrated')['payload']
        publication=self.store.receipt(integrated['publication'],kind='publication')
        return (publication['binding']['task']==task.id and publication['binding']['contract']==digest(body)
                and publication['binding']['release']==body['release'] and publication['payload']['pr']==task.completion_contract)

    def admit(self,task):
        """Per-card spawn fence: bad contracts cannot starve unrelated diagnosis."""
        body=json.loads(task.body)
        if body.get('kind') not in ('tests','implementation','integration'):return
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            anchor=kb.get_task(conn,body.get('release_anchor'))
            if not anchor or anchor.status!='blocked':raise ValueError('active release anchor required')
            graph=self.store.receipt(json.loads(self.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')
            if graph['binding']!=self.binding(anchor) or graph['payload']['project']!=self.project.fingerprint():raise ValueError('graph scope changed')
            if graph['payload'].get('validation_bundle')!=validation_files(self.project,self.store)[0]:raise ValueError('release validation bundle changed')
            card=next((item['cards'][body['kind']] for item in graph['payload']['items'] if item['package']['id']==body.get('package')),None)
            if not card or card['id']!=task.id:raise ValueError('graph-owned assignment required')
            self.check_card(conn,card)

    def prepare(self,run,quality):
        """Admit only graph-owned work; seed empty test workspaces, never reset."""
        self.board.ensure(run);kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            body=json.loads(kb.get_task(conn,run.task).body)
            anchor=kb.get_task(conn,body.get('release_anchor'))
            if not anchor or anchor.status!='blocked' or self.intake.terminal(anchor):raise ValueError('active release graph required')
            record=self.store.receipt(json.loads(self.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')
            if record['binding']!=self.binding(anchor) or record['payload']['project']!=self.project.fingerprint():raise ValueError('foreign graph')
            if record['payload'].get('validation_bundle')!=validation_files(self.project,self.store)[0]:raise ValueError('release validation bundle changed')
            card=next((item['cards'][run.kind] for item in record['payload']['items']
                       if item['package']['id']==body.get('package')),None)
            if not card or card['id']!=run.task or card['owner']!=run.author:raise ValueError('current graph-owned assignment required')
            self.check_card(conn,card)
        if run.kind=='tests' and not run.reviewing:
            source=self.baseline(run,body);workspace=self.board.workspace(run)
            if not any(workspace.iterdir()):self.store.checkout(source,workspace)
            else:
                from .repairs import repair_authority
                authority=repair_authority(self.project,self.store,self.board,run)
                if authority and authority['proposal']['classification']=='test_contract':
                    left,right=self.store.manifest(source),self.store.manifest(self.store.capture(workspace))
                    if any(p not in authority['proposal']['test_paths'] and left.get(p)!=right.get(p) for p in set(left)|set(right)):
                        raise ValueError('correction workspace changed an unauthorized file')
                else:quality.protect(source,self.store.capture(workspace))
        review=self.store.receipt(body['release_plan'],kind='plan_review')
        proposed=self.store.receipt(review['payload']['plan'],kind='work_plan')
        _,brief=self.intake.approved(proposed['payload']['approval'])
        if run.kind=='tests' and not run.reviewing:snapshot=source
        elif run.kind=='implementation' and not run.reviewing:snapshot=quality.freeze(run,self.board.input(run,'tests'))['snapshot']
        elif run.kind=='integration':snapshot=self.store.receipt(self.board.input(run,'delivery'),kind='delivery_review')['payload']['snapshot']
        else:
            key='red' if run.kind=='tests' else 'green'
            receipt=self.board.input(run,key,review_handoff=True)
            snapshot=(quality.test_evidence(receipt) if key=='red' else self.store.receipt(receipt,kind=key))['payload']['snapshot']
        folder=self.store.tree(snapshot)/self.project.tests_dir
        from .executor import browser_contract
        from .browser import acceptance_manifest
        mode=browser_contract(self.project,self.store)
        try:existing=(list(acceptance_manifest(folder,allow_empty=True)['criteria']) if mode==2 else
            [item['id'] for item in load_contract(folder)['checks']] if list(folder.glob('qa*.json')) else [])
        except (ValueError,OSError):existing='InvalidBrowserContract: review the immutable files; do not weaken existing scenarios'
        controls=(quality.freeze(run,self.board.input(run,'tests'))['control_cases'] if run.kind=='implementation' else None)
        from .repairs import repair_authority,context_view
        authority=repair_authority(self.project,self.store,self.board,run)
        technical=authority['context'] if authority else proposed['payload']['document']
        result=dict(approved_brief=brief['payload']['document'],
            brief_authority=self.intake.authority(proposed['payload']['approval'],run.release),package=body['package'],criteria=body['criteria'],
            repair=({**authority,'context':context_view(self.store,authority['context'])} if authority else None),
            required_control_cases=controls,
            architecture=technical['architecture'],observability=technical['observability'],
            execution=execution_context(self.project,browser_mode=mode),baseline=snapshot,existing_qa=existing,
            browser_protocol=author_protocol(mode),
            acceptance=body['acceptance'],stack='qualified Python HTTP, port 8080, /health and /identity; no downloads/network in workers',
            tdd='Tests author: change tests only; Red requires a real failing assertion in a new test body, not import/discovery/runtime errors. '
                'If existing baseline tests already fail, submit the UNCHANGED baseline to confirm a known regression at the controller SHA; '
                'independent review must validate all exact existing failures before a product-only fix. Never duplicate tests to bypass baseline failure. '
                'Never change old tests/configs or reduce discovery. Implementer: Green uses the exact frozen inventory. '
                'delivery_submit mutations are disposable full replacements or exact before/after edits of existing product files; never tests/configs. '
                'Controls must fail by assertions and collectively cover every required_control_cases target frozen by independent review. '
                'Passing auxiliary tests remain protected and run in the complete suite; never corrupt tests to kill a mutant. '
                'Controller executes all evidence, never accept prose pass claims. '
                'Tests author and reviewer are part of the team: they may pin selectors and deterministic UI wording where the approved brief delegates those choices. '
                'Treat those frozen choices as the implementation contract, not new CEO decisions; never add out-of-scope requirements. '
                'Use actual browser_protocol operations, not hypothetical unsupported assertions.',
            browser='Add only missing criterion IDs in '+self.project.tests_dir+'/qa.'+body['package']+'-'+run.release[:12]+'.json; '
                'preserve every old QA contract and avoid duplicate IDs. Follow browser_protocol, including exact field names.')
        if authority and authority['proposal']['classification']=='test_contract':
            result['tdd']='Technical QA-expectation correction, not new functionality. Historical Red and every unittest/control target remain preserved. Test author may correct only expected text in repair.proposal.test_paths, citing the approved brief. delivery_submit records test_revision, not a new Red. Reviewer independently checks the correction and freezes a new revision. Implementer uses unchanged frozen tests and must run Green and all required negative controls.'
            result['browser']='Change only expected text in the explicitly authorized existing QA files; preserve all IDs, actions, selectors, paths and unit tests. Match the brief and deterministic UI wording; do not add requirements or weaken business coverage.'
        if mode==2:
            result['browser']='Add acceptance_*.py tests subclassing AcceptanceTest and acceptance.*.json criterion coverage. The same frozen suite runs in preview and deployment; use self.target and self.new_context(). Preserve every existing test/manifest. Review behavior coverage independently, including timing and independent sessions where required.'
        if body.get('continuation_plan'):
            from .repairs import reviewed
            graph=self.store.receipt(json.loads(self.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')['payload']
            continuation=reviewed(self.project,self.store,graph['continuation_review'])
            if continuation['task']!=body['continuation_plan']:raise ValueError('exact continuation review required')
            if continuation['context'].get('repair_kind')=='fixture':
                result['fixture_revision']=context_view(self.store,continuation['context'])
                if run.kind=='tests' and authority:
                    result['tdd']=('Correct only additive setup in repair.proposal.test_paths. Preserve every old statement, assertion, '
                        'selector, timeout, helper and manifest. Independently review setup/action/assertion, not only failure status. '
                        'delivery_submit executes the original published baseline and a fresh Red with the corrected candidate. '
                        'It cannot reuse old Red or approve the new fixture. Independent test review freezes a new version, '
                        'preserving the complete old inventory and negative-control targets. No product changes.')
                    result['browser']='Use only the existing browser protocol and helpers; fix the reviewed missing setup without changing business coverage.'
                elif run.kind=='implementation' and authority:
                    result['tdd']=('Continue preserved product work using the newly reviewed frozen tests. Use delivery_validate for the full suite, '
                        'then submit fresh Green and the complete negative-control set for this exact revision. '
                        'Do not change tests, reuse old Green or infer approval from the fixture repair proposal.')
            else:result['submission_continuation']=continuation_context(continuation)
        return result

    def baseline(self,run,body):
        source=self.board.input(run,'baseline');reference=body['inputs']['baseline']
        if reference.startswith('parent:'):
            _,parent,key=reference.split(':',2)
            if key!='baseline':raise ValueError('typed integrated baseline required')
            _,qa,_=self.closed(parent,'release_evidence','release_evidence')
            artifact=self.store.receipt(qa['payload']['artifact'],kind='artifact')['payload']
            if (qa['binding']['release']!=run.release or artifact['project']!=self.project.fingerprint()
                    or artifact['snapshot']!=source):raise ValueError('baseline must match exact independent parent QA')
        return source

    def package_evidence(self,item,previous):
        if item.get('repair_context'):
            context=self.store.receipt(item['repair_context'],kind='repair_context')['payload']
            base=previous;history=context
            while history['prior'].get('repair_context'):
                history=self.store.receipt(history['prior']['repair_context'],kind='repair_context')['payload']
            if history['prior_base_commit']!=base['commit'] or history['prior_base_snapshot']!=base['snapshot']:
                raise ValueError('corrective history must extend the original integrated package base')
            frozen=Quality(self.project,self.store,None,self.board).frozen_plan(self.store.receipt(context['tests'],kind='tests_frozen'))
            previous=dict(snapshot=context['snapshot'],commit=context['commit'],cases=sorted(set(previous.get('cases',[]))|set(frozen['cases'])))
        cards=item['cards'];tests,frozen,_=self.closed(cards['tests']['id'],'tests','tests_frozen')
        frozen_plan=Quality(self.project,self.store,None,self.board).frozen_plan(frozen)
        delivery,review,_=self.closed(cards['implementation']['id'],'delivery','delivery_review')
        qa_id,qa,handoff=self.closed(cards['integration']['id'],'release_evidence','release_evidence')
        red=Quality(self.project,self.store,None,self.board).test_evidence(frozen['payload']['red']);green=self.store.receipt(review['payload']['green'],kind='green')
        controls=self.store.receipt(review['payload']['controls'],kind='controls')
        artifact=self.store.receipt(qa['payload']['artifact'],kind='artifact')
        integrated=self.store.receipt(qa['payload']['integrated'],kind='integrated')
        publication=self.store.receipt(integrated['payload']['publication'],kind='publication')
        if (green['payload']['freeze']!=tests or review['payload']['verdict']['decision']!='approve'
                or controls['payload'].get('control_contract')!=CONTROL_CONTRACT
                or not set(frozen_plan['control_cases'])<=set(controls['payload']['coverage'])
                or controls['payload']['green']!=review['payload']['green'] or controls['binding']!=green['binding']
                or green['binding']['task']!=cards['implementation']['id'] or red['binding']['task']!=cards['tests']['id']
                or red['payload']['baseline']!=previous['snapshot'] or publication['payload']['base_sha']!=previous['commit']
                or publication['payload']['review']!=delivery or artifact['payload']['review']!=delivery
                or artifact['payload']['snapshot']!=review['payload']['snapshot'] or integrated['payload']['snapshot']!=review['payload']['snapshot']
                or artifact['payload']['integrated']!=qa['payload']['integrated'] or handoff.get('rollout')!=qa['payload']['rollout']
                or qa['payload']['commit']!=artifact['payload']['commit'] or qa['payload']['commit']!=integrated['payload']['commit']
                or qa['payload']['image']!=artifact['payload']['image'] or not qa['payload']['rollback_verified']
                or not set(previous.get('cases',[]))<=set(green['payload']['cases'])):
            raise ValueError('each package requires exact reviewed TDD, integrated base, deployed QA and rollback')
        self.store.tree(artifact['payload']['snapshot'])
        return dict(package=item['package']['id'],criteria=item['package']['criteria'],tests=tests,delivery=delivery,
            **({'repair_context':item['repair_context']} if item.get('repair_context') else {}),
            qa=qa_id,commit=qa['payload']['commit'],snapshot=artifact['payload']['snapshot'],cases=green['payload']['cases'],
            checks=qa['payload']['checks'],pr=publication['payload']['pr'])

    def accepted_rollback(self,release,seed):
        """A new release starts from its last accepted deployment, not bootstrap.

        Historical memory is not an approval of the new release. Intake checks
        its native acceptance provenance; here it only selects the exact prior
        rollback image. An externally changed seed requires explicit diagnosis.
        """
        previous=self.intake.previous(release)
        if previous is None:return None
        accepted=self.store.receipt(previous['acceptance'],kind='release_acceptance')
        data=accepted['payload'];qa=self.store.receipt(data['final_qa'],kind='release_evidence')
        artifact_id=qa['payload']['artifact'];artifact=self.store.receipt(artifact_id,kind='artifact')
        proof,image=qa['payload'],artifact['payload'];owner,reviewer=artifact['binding'],qa['binding']
        if (data['project']!=self.project.fingerprint() or proof['project']!=data['project'] or image['project']!=data['project']
                or seed['project']!=data['project'] or data['state']!='HOMOLOGADA' or image['role']!='candidate'
                or data['qualification'] is not self.project.qualification or data['delivery_approval'] is not (not self.project.qualification)
                or data['commit']!=previous['commit'] or seed['commit']!=data['commit'] or image['snapshot']!=seed['snapshot']
                or not proof['rollback_verified'] or any(proof[key]!=data[key] or image[key]!=data[key] for key in ('commit','image'))
                or owner['release']!=accepted['binding']['release'] or owner['release']==release
                or any(reviewer[key]!=owner[key] for key in ('task','contract','release','author','kind'))
                or owner['kind']!='integration' or owner['reviewing'] is not False or owner['actor']!=owner['author']
                or reviewer['reviewing'] is not True or reviewer['actor']==owner['author']
                or reviewer['actor'] not in self.project.reviewers_for(owner['author'])):
            raise ValueError('rollback must match exact prior homologation, independent QA and current release seed')
        self.store.tree(image['snapshot'])
        return artifact_id

    def rollback_artifact(self,run):
        self.board.ensure(run);kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            body=json.loads(kb.get_task(conn,run.task).body);anchor=kb.get_task(conn,body['release_anchor'])
        if body.get('repair_plan'):
            from .repairs import repair_authority
            return repair_authority(self.project,self.store,self.board,run)['context']['artifact']
        graph=self.store.receipt(json.loads(self.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')['payload']
        for index,item in enumerate(graph['items']):
            if item['cards']['integration']['id']!=run.task:continue
            if not index:
                seed=self.store.receipt(graph['seed'],kind='release_seed')['payload']
                return self.accepted_rollback(run.release,seed)
            _,qa,_=self.closed(graph['items'][index-1]['cards']['integration']['id'],'release_evidence','release_evidence')
            return qa['payload']['artifact']
        raise ValueError('integration is not part of its current graph')

    def accept(self,conn,anchor,specification,graph_id,graph,services):
        kb,_,_=native()
        if not all(kb.get_task(conn,card['id']).status=='done' for item in graph['items'] for card in item['cards'].values()):return None
        prior=self.store.receipt(graph['seed'],kind='release_seed')['payload'];evidence=[]
        for item in graph['items']:
            prior=self.package_evidence(item,prior);evidence.append(prior)
        final=evidence[-1];criteria={item['id'] for item in specification['brief']['criteria']}
        if not criteria<=set(final['checks']):raise ValueError('final deployed QA must cover every approved criterion')
        qa=self.store.receipt(final['qa'],kind='release_evidence')['payload']
        deployment=Deployment(self.project,self.store,self.board,None);artifact=deployment.read_artifact(qa['artifact'])
        live=deployment.service(artifact)
        if not live or not live['healthy'] or any(live[key]!=qa[key] for key in ('container','image','url')):
            raise EffectBlocked('the exact QA-qualified deployment is no longer healthy/current')
        last=graph['items'][-1]['cards']['integration']['id']
        repository,github=services(self.project.delivery_roles['integration'],task=last)
        if repository.remote_head(self.project.branch)!=final['commit']:raise EffectBlocked('release branch advanced after QA')
        ci=github.accept(final['pr'],final['commit'])
        publication=Publication(self.project,self.store,self.board,repository,github)
        if publication.local_ci:
            integrated=self.store.receipt(qa['integrated'],kind='integrated')['payload']
            published=self.store.receipt(integrated['publication'],kind='publication')['payload']
            proof=publication.local_ci.existing(final['commit'],published['base_sha'],stage='integrated')
            if integrated.get('local_ci')!=proof:raise EffectBlocked('final CI provenance changed since integrated validation')
        publication.require_ci(ci,final['commit'],time.time())
        if self.board.guard:self.board.guard()
        acceptance=self.store.record('release_acceptance',self.binding(anchor),dict(project=self.project.fingerprint(),
            state='HOMOLOGADA',qualification=self.project.qualification,delivery_approval=not self.project.qualification,
            **({'validation_bundle':graph['validation_bundle']} if graph.get('validation_bundle') else {}),
            brief=specification['approval'],plan_review=specification['review'],graph=graph_id,packages=evidence,
            criteria=sorted(criteria),final_qa=final['qa'],commit=final['commit'],image=qa['image'],url=qa['url'],ci=ci))
        if not kb.complete_task(conn,anchor.id,summary='HOMOLOGADA'+(' — deterministic qualification only' if self.project.qualification else ''),
                metadata={'release_acceptance':acceptance}):raise ValueError('native release acceptance refused')
        return acceptance

    def reconcile(self,conn,services):
        if not self.project.delivery_roles:return {}
        kb,_,_=native();issues={}
        with self.journal.lock(['releases',self.project.fingerprint()]):
            for anchor in self.intake.roots(conn):
                try:
                    if self.intake.terminal(anchor):continue
                    if anchor.status!='blocked':raise ValueError('release anchor changed without terminal evidence')
                    spec=self.specification(conn,anchor)
                    if spec is None:continue
                    graph_id,graph=self.materialize(conn,anchor,spec,services)
                    from .repairs import Repairs
                    repairs=Repairs(self)
                    effective=repairs.continue_submission(conn,anchor,spec,graph)
                    effective=repairs.continue_review(conn,anchor,effective)
                    effective=repairs.reconcile(conn,anchor,spec,effective,services)
                    if effective!=graph:
                        graph=effective;graph_id=self.store.record('release_graph',self.binding(anchor),graph)
                    self.accept(conn,anchor,spec,graph_id,graph,services)
                except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError,EffectBlocked,Pending) as error:
                    issues[anchor.id]=dict(category=type(error).__name__,detail=str(error)[:500],owner=self.project.coordination_roles['lead'])
        return issues
