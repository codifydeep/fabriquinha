"""Business intake and reviewed plans on native cards, not another release DB.

Local operator CLI is the trusted CEO channel. No agent tool can approve a
brief, release budget, create arbitrary cards or declare a release homologated.
"""
import argparse
import json
import re
from pathlib import Path
from .artifacts import digest, encoded
from .effects import Journal
from .kanban_lane import native
from .config import execution_context

HUMAN_REVIEWER='fabriquinha-ceo'  # Reserved human identity, never an installed model profile.

def text(value, limit=4000):
    if not isinstance(value,str) or not 1<=len(value.strip())<=limit or '\0' in value:
        raise ValueError('bounded nonempty text required')
    return value


def texts(value, *, minimum=0, maximum=16):
    if not isinstance(value,list) or not minimum<=len(value)<=maximum:
        raise ValueError('bounded text list required')
    for item in value:text(item)


def brief(value):
    if not isinstance(value,dict) or set(value)!={'summary','criteria','out_of_scope','assumptions','observability'}:
        raise ValueError('summary, acceptance criteria, exclusions, assumptions and instrumentation required')
    text(value['summary'],12000);text(value['observability'])
    texts(value['out_of_scope']);texts(value['assumptions'])
    criteria=value['criteria']
    if not isinstance(criteria,list) or not 1<=len(criteria)<=24:
        raise ValueError('one to 24 verifiable acceptance criteria required')
    seen=set()
    for item in criteria:
        if (not isinstance(item,dict) or set(item)!={'id','statement'}
                or not isinstance(item['id'],str) or not re.fullmatch('[A-Z][A-Z0-9_-]{0,31}',item['id'])
                or item['id'] in seen):raise ValueError('unique criterion identity required')
        text(item['statement']);seen.add(item['id'])
    if len(encoded(value))>64000:raise ValueError('brief exceeds context bound')
    return value


def plan(value, approved, project):
    if not isinstance(value,dict) or set(value)!={'architecture','tasks','observability'}:
        raise ValueError('architecture, work DAG and instrumentation decision required')
    text(value['architecture'],12000);text(value['observability'])
    tasks=value['tasks'];criteria={item['id'] for item in approved['criteria']}
    if not isinstance(tasks,list) or not 1<=len(tasks)<=24:raise ValueError('bounded work DAG required')
    graph={};covered=set()
    for item in tasks:
        if (not isinstance(item,dict) or set(item)!={'id','title','owner','depends_on','criteria','acceptance'}
                or not isinstance(item['id'],str) or not re.fullmatch('[a-z][a-z0-9_-]{0,31}',item['id'])
                or item['id'] in graph or not isinstance(item['owner'],str)
                or item['owner'] not in project.reviewers):raise ValueError('unique work id and configured reviewed owner required')
        text(item['title'],200);text(item['acceptance'])
        texts(item['depends_on'],maximum=24);texts(item['criteria'],minimum=1,maximum=24)
        if len(set(item['depends_on']))!=len(item['depends_on']) or len(set(item['criteria']))!=len(item['criteria']):
            raise ValueError('duplicate dependency or criterion')
        if not set(item['criteria'])<=criteria:raise ValueError('plan cannot introduce unapproved criteria')
        graph[item['id']]=set(item['depends_on']);covered.update(item['criteria'])
    remaining={key:set(deps) for key,deps in graph.items()}
    while remaining:
        ready={key for key,deps in remaining.items() if not deps}
        if not ready:raise ValueError('acyclic DAG with known dependencies required')
        remaining={key:deps-ready for key,deps in remaining.items() if key not in ready}
    if covered!=criteria:raise ValueError('plan must cover the complete approved brief')
    if len(encoded(value))>64000:raise ValueError('plan exceeds context bound')
    return value


class Intake:
    def __init__(self,project,store,board):
        self.project,self.store,self.board=project,store,board
        self.journal=Journal(store.root/'effects')

    def lock(self):return self.journal.lock(['intake',self.project.fingerprint()])

    def roots(self,conn):
        kb,_,_=native();result=[]
        for row in conn.execute('SELECT id,body FROM tasks ORDER BY created_at,id'):
            try:body=json.loads(row['body'] or '{}')
            except ValueError:continue
            if body.get('kind')=='release':
                if body.get('version')!=1 or body.get('project')!=self.project.fingerprint():
                    raise ValueError('release anchor configuration drift')
                result.append(kb.get_task(conn,row['id']))
        return result

    def start(self,value):
        if not self.project.coordination_roles:raise ValueError('configure explicit product/lead roles first')
        if not isinstance(value,dict) or set(value)!={'request','label','objective'}:
            raise ValueError('operator request key, release label and original objective required')
        text(value['objective'],24000);text(value['label'],80)
        if not isinstance(value['request'],str) or not re.fullmatch('[a-zA-Z0-9_-]{1,80}',value['request']):
            raise ValueError('stable operator request key required')
        kb,kbc,_=native()
        with self.lock(),kbc.connect_closing() as conn:
            key=digest([self.project.fingerprint(),'release',value['request']]);roots=self.roots(conn)
            old=next((task for task in roots if json.loads(task.body)['release']==key),None)
            if old:
                if json.loads(old.body)['request']!=value:raise ValueError('request key reused with another objective')
            elif any(not self.terminal(task) for task in roots):
                raise ValueError('one active release; raw done is not qualified terminal evidence')
            else:
                anchor=kb.create_task(conn,title='RELEASE '+value['label'],assignee=self.project.coordination_roles['lead'],
                    body=json.dumps(dict(version=1,kind='release',release=key,project=self.project.fingerprint(),request=value)),
                    initial_status='blocked',completion_contract='local-only',idempotency_key=key)
                old=kb.get_task(conn,anchor)
            self._reconcile(conn)
            return dict(release=old.id,execution=key,delivery_approval=False)

    def _card(self,conn,anchor,kind,*,approval=None):
        kb,_,_=native();body=json.loads(anchor.body);roles=self.project.coordination_roles
        values=dict(version=1,kind=kind,release=body['release'],anchor=anchor.id,inputs={})
        if approval:values['inputs']['approved_brief']=approval
        else:values['objective']=body['request']['objective']
        task_id=kb.create_task(conn,title=kind.upper()+' '+body['request']['label'],
            body=json.dumps(values),assignee=roles['product' if kind=='brief' else 'lead'],
            workspace_kind='scratch',completion_contract='local-only',max_retries=2,max_runtime_seconds=600,
            parents=[self.approved(approval)[0]['binding']['task']] if approval else [],
            idempotency_key=digest([body['release'],kind]))
        existing=kb.get_task(conn,task_id)
        if json.loads(existing.body)!=values or existing.completion_contract!='local-only':
            raise ValueError('coordination card contract drift; never overwrite ongoing work')
        return task_id

    def approved(self,approval):
        record=self.store.receipt(approval,kind='brief_approval');data=record['payload'];binding=record['binding']
        proposal=self.store.receipt(binding['brief'],kind='product_brief')
        if (binding.get('actor')!='ceo' or data.get('decision')!='approve' or data.get('project')!=self.project.fingerprint()
                or proposal['payload']['project']!=self.project.fingerprint()
                or proposal['binding']['task']!=binding['task'] or proposal['binding']['release']!=binding['release']):
            raise ValueError('exact business approval required')
        brief(proposal['payload']['document'])
        return record,proposal

    def terminal(self,anchor):
        if anchor.status!='done':return False
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:row=kb.latest_run(conn,anchor.id)
        if not row or row.outcome!='completed' or not row.metadata or 'release_acceptance' not in row.metadata:return False
        record=self.store.receipt(row.metadata['release_acceptance'],kind='release_acceptance');body=json.loads(anchor.body)
        expected=dict(actor='controller',task=anchor.id,release=body['release'],contract=digest(body))
        data=record['payload']
        if (record['binding']!=expected or data['project']!=self.project.fingerprint() or data['state']!='HOMOLOGADA'
                or data['qualification'] is not self.project.qualification or data['delivery_approval'] is not (not self.project.qualification)):
            raise ValueError('scoped final release acceptance required')
        return True

    def _reconcile(self,conn):
        if not self.project.coordination_roles:return
        kb,_,_=native()
        for anchor in self.roots(conn):
            if self.terminal(anchor):continue
            if anchor.status!='blocked':raise ValueError('release anchor changed without qualified terminal evidence')
            task_id=self._card(conn,anchor,'brief');task=kb.get_task(conn,task_id)
            if task.status!='done':continue
            row=kb.latest_run(conn,task_id)
            if not row or row.outcome!='completed' or not row.metadata or 'approved_brief' not in row.metadata:
                raise ValueError('brief completed without business approval; release remains unqualified')
            approval=row.metadata['approved_brief'];record,proposal=self.approved(approval)
            if (record['binding']['task']!=task.id or record['binding']['release']!=json.loads(anchor.body)['release']
                    or proposal['binding']['contract']!=digest(json.loads(task.body))
                    or proposal['binding']['actor']!=self.project.coordination_roles['product']):
                raise ValueError('approved brief card or author changed')
            self._card(conn,anchor,'plan',approval=approval)

    def reconcile(self,conn):
        with self.lock():self._reconcile(conn)

    def pending(self,conn,task_id):
        kb,_,_=native();task=kb.get_task(conn,task_id)
        if not task or task.status!='review' or task.assignee!=HUMAN_REVIEWER:return None
        body=json.loads(task.body)
        if body.get('kind')!='brief':return None
        row=conn.execute("SELECT e.run_id,r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(task_id,)).fetchone()
        values=json.loads(row['metadata']) if row and row['metadata'] else {}
        if set(values)!={'request','audience','scope'} or values.get('audience')!='ceo' or values.get('scope')!='product':
            raise ValueError('scoped product wait required')
        record=self.store.receipt(values['request']);binding=record['binding']
        if (record['kind'] not in ('product_brief','product_question') or record['payload']['project']!=self.project.fingerprint()
                or binding['task']!=task.id or binding['release']!=body['release'] or binding['contract']!=digest(body)
                or binding['number']!=row['run_id'] or binding['actor']!=(self.project.coordination_roles or {}).get('product')):
            raise ValueError('exact pending product document required')
        return dict(task=task_id,request=values['request'],audience='ceo',scope='product',
                    kind=record['kind'],document=record['payload']['document'],delivery_approval=False)

    def respond(self,task_id,expected,decision,answer):
        """Only the local operator entry point; not registered as an agent tool."""
        if decision not in ('approve','changes','answer'):raise ValueError('scoped business response required')
        text(answer);kb,kbc,_=native()
        with self.lock(),kbc.connect_closing() as conn:
            task=kb.get_task(conn,task_id)
            if not task or not self.project.coordination_roles:raise ValueError('product brief card required')
            body=json.loads(task.body)
            if body.get('kind')!='brief' or task.assignee!=HUMAN_REVIEWER:
                raise ValueError('response cannot resolve a technical or unrelated card')
            if task.status=='done' and decision=='approve':
                row=kb.latest_run(conn,task.id);approval=(row.metadata or {}).get('approved_brief') if row else None
                if approval and self.approved(approval)[0]['binding']['brief']==expected:
                    self._reconcile(conn);return dict(status='brief_approved',approval=approval,delivery_approval=False)
            event=conn.execute("SELECT e.run_id,e.payload,r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
                "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(task_id,)).fetchone()
            reason=json.loads(event['metadata']) if event else {}
            origin=json.loads(event['payload']) if event else {}
            if (task.status!='review' or reason!=dict(request=expected,audience='ceo',scope='product')
                    or origin.get('implementer')!=self.project.coordination_roles['product']
                    or origin.get('reviewer')!=HUMAN_REVIEWER):
                raise ValueError('exact outstanding product question/proposal required')
            kind='product_question' if decision=='answer' else 'product_brief'
            request=self.store.receipt(expected,kind=kind)
            binding=request['binding']
            if (request['payload']['project']!=self.project.fingerprint() or binding['task']!=task.id
                    or binding['release']!=body['release'] or binding['contract']!=digest(body)
                    or binding['number']!=event['run_id'] or binding['actor']!=self.project.coordination_roles['product']):
                raise ValueError('stale or foreign product response')
            response=self.store.record('brief_approval' if decision=='approve' else 'product_answer',
                dict(actor='ceo',task=task.id,release=body['release'],brief=expected),
                dict(project=self.project.fingerprint(),decision=decision,text=answer))
            if decision=='approve':
                if not kb.complete_task(conn,task.id,summary='CEO approved this exact product brief',metadata={'approved_brief':response}):
                    raise ValueError('native business completion refused')
                self._reconcile(conn)
            else:
                # Record before releasing only this card; a repeated response
                # cannot unblock a newer question. This never releases budget.
                comment=json.dumps(dict(request=expected,response=response,decision=decision,text=answer))
                if not any(item.author=='ceo' and item.body==comment for item in kb.list_comments(conn,task.id)):
                    kb.add_comment(conn,task.id,'ceo',comment)
                if not kb.reopen_review_task(conn,task.id):raise ValueError('native product resume refused')
            return dict(status='brief_approved' if decision=='approve' else 'product_resumed',response=response,delivery_approval=False)


class DraftActivity:
    """Document-only phase. No terminal/backend, files, Docker or admin handler."""
    def __init__(self,project,store,board,run):
        self.project,self.store,self.board,self.run=project,store,board,run
        self.ensure()
        if run.kind not in ('brief','plan'):raise ValueError('document activity required')
    def ensure(self):self.board.ensure(self.run)
    def close(self):pass


class DraftTools:
    def __init__(self,activity):
        self.a=activity;self.run=activity.run;self.intake=Intake(activity.project,activity.store,activity.board)

    def evidence(self):
        self.a.ensure();kb,kbc,_=native()
        with kbc.connect_closing() as conn:body=json.loads(kb.get_task(conn,self.run.task).body)
        if self.run.kind=='brief':return dict(original_objective=body['objective'],execution=execution_context(self.a.project))
        approval=self.a.board.input(self.run,'approved_brief');record,proposal=self.intake.approved(approval)
        if record['binding']['release']!=self.run.release:raise ValueError('foreign approved brief')
        result=dict(approved_brief=proposal['payload']['document'],available_owners=list(self.a.project.reviewers),
                    execution=execution_context(self.a.project))
        if self.run.reviewing:
            receipt=self.a.store.receipt(self.a.board.input(self.run,'plan',review_handoff=True),kind='work_plan')
            origin=receipt['binding']
            if (origin['task']!=self.run.task or origin['contract']!=self.run.contract or origin['actor']!=self.run.author
                    or origin['release']!=self.run.release or receipt['payload']['project']!=self.a.project.fingerprint()
                    or receipt['payload']['approval']!=approval):raise ValueError('exact independent plan handoff required')
            result['plan']=receipt['payload']['document']
        return result

    def submit(self,args):
        self.a.ensure()
        if self.run.reviewing:raise ValueError('review cannot replace the plan')
        document=brief(args) if self.run.kind=='brief' else plan(args,self.evidence()['approved_brief'],self.a.project)
        if self.run.kind=='brief' and self.a.project.delivery_roles and len(document['criteria'])>20:
            raise ValueError('the qualified browser contract supports at most 20 acceptance criteria')
        payload=dict(project=self.a.project.fingerprint(),document=document)
        if self.run.kind=='plan':payload['approval']=self.a.board.input(self.run,'approved_brief')
        receipt=self.a.store.record('product_brief' if self.run.kind=='brief' else 'work_plan',self.run.binding(),payload)
        if self.run.kind=='brief':return self.park(receipt)
        self.a.board.review(self.run,'Independent architecture and complete brief coverage review',{'plan':receipt})
        return dict(status='plan_review_requested',plan=receipt,delivery_approval=False)

    def question(self,args):
        self.a.ensure()
        if self.run.kind!='brief' or self.run.reviewing or not isinstance(args,dict) or set(args)!={'question','context','options'}:
            raise ValueError('only product may ask a scoped user/business question')
        text(args['question']);text(args['context']);texts(args['options'],minimum=2,maximum=4)
        receipt=self.a.store.record('product_question',self.run.binding(),dict(project=self.a.project.fingerprint(),document=args))
        return self.park(receipt)

    def park(self,receipt):
        self.a.ensure();kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            # Native human review does not count repeated business clarification
            # as an infrastructure block loop. No synthetic CEO/model run.
            if not kb.request_review(conn,self.run.task,reviewer=HUMAN_REVIEWER,summary='CEO business input required',
                    metadata=dict(request=receipt,audience='ceo',scope='product'),
                    expected_run_id=self.run.number):raise ValueError('native product wait refused')
        return dict(status='waiting_for_ceo',request=receipt,delivery_approval=False)

    def review(self,args):
        evidence=self.evidence()
        if not self.run.reviewing or self.run.kind!='plan' or self.run.actor==self.run.author:
            raise ValueError('independent plan review required')
        if not isinstance(args,dict) or set(args)!={'decision','reason','findings'} or args['decision'] not in ('approve','changes'):
            raise ValueError('structured plan review required')
        text(args['reason']);texts(args['findings'],maximum=8)
        if (args['decision']=='approve')!= (not args['findings']):raise ValueError('concrete findings required for changes')
        plan(evidence['plan'],evidence['approved_brief'],self.a.project)
        receipt=self.a.store.record('plan_review',self.run.binding(),dict(project=self.a.project.fingerprint(),verdict=args,
            plan=self.a.board.input(self.run,'plan',review_handoff=True)))
        self.a.board.finish_review(self.run,args['reason'],{'plan_review':receipt},changes=args['decision']=='changes')
        return dict(status='plan_approved' if args['decision']=='approve' else 'plan_changes_requested',review=receipt,delivery_approval=False)


def register_draft(activity,on_terminal):
    from tools.registry import registry
    operations=DraftTools(activity)
    names={'plan_review':operations.review} if activity.run.reviewing else (
        {'brief_submit':operations.submit,'brief_question':operations.question} if activity.run.kind=='brief' else {'plan_submit':operations.submit})
    # Full closed schemas are generated from fixed examples below, never by a worker.
    string=dict(type='string',minLength=1,maxLength=4000)
    array=dict(type='array',items=string,maxItems=16)
    criterion=dict(type='object',additionalProperties=False,required=['id','statement'],properties=dict(id=string,statement=string))
    work=dict(type='object',additionalProperties=False,required=['id','title','owner','depends_on','criteria','acceptance'],
        properties=dict(id=string,title=string,owner=string,depends_on=array,criteria=array,acceptance=string))
    properties=dict(
        brief_submit=dict(summary=dict(type='string',minLength=1,maxLength=12000),criteria=dict(type='array',minItems=1,maxItems=24,items=criterion),
                          out_of_scope=array,assumptions=array,observability=string),
        brief_question=dict(question=string,context=string,options=dict(type='array',minItems=2,maxItems=4,items=string)),
        plan_submit=dict(architecture=dict(type='string',minLength=1,maxLength=12000),tasks=dict(type='array',minItems=1,maxItems=24,items=work),observability=string),
        plan_review=dict(decision=dict(type='string',enum=['approve','changes']),reason=string,findings=dict(type='array',maxItems=8,items=string)))
    for name,operation in names.items():
        def handler(args,operation=operation,**kwargs):
            result=operation(args)
            if on_terminal:on_terminal(result)
            return json.dumps(result)
        registry.register(name=name,toolset='fabriquinha_delivery',schema=dict(name=name,
            description='Submit the current business document or independent plan review. No delivery/budget/admin authority.',
            parameters=dict(type='object',additionalProperties=False,required=list(properties[name]),properties=properties[name])),handler=handler)
    return set(names),operations


def main():
    from .runtime import Runtime
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('start','respond','show'))
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--file',type=Path);parser.add_argument('--task');parser.add_argument('--expect')
    parser.add_argument('--decision',choices=('approve','changes','answer'));parser.add_argument('--text')
    args=parser.parse_args();runtime=Runtime(args.root,args.upstream)
    if args.operation=='show':
        _,kbc,_=native()
        with kbc.connect_closing() as conn:value=runtime.intake.pending(conn,args.task)
    else:
        value=(runtime.intake.start(json.loads(args.file.read_bytes())) if args.operation=='start'
               else runtime.intake.respond(args.task,args.expect,args.decision,args.text))
    print(json.dumps(value,indent=2))


if __name__=='__main__':main()
