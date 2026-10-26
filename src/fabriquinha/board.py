"""Authenticate a current Hermes run at the controller edge; no extra board DB."""
from dataclasses import dataclass, asdict, replace
import json
from pathlib import Path
from .artifacts import digest
from .kanban_lane import native


@dataclass(frozen=True)
class Run:
    task: str
    number: int
    actor: str
    kind: str
    reviewing: bool
    author: str
    release: str
    contract: str

    def binding(self):
        return asdict(self)

    def subject(self):
        """Stable effect scope, NOT authorization or an approval binding.

        The controller must still ensure the current claim before each effect.
        An immutable review receipt further identifies the delivery revision.
        """
        return {key: value for key, value in self.binding().items() if key != 'number'}

    def same_subject(self, binding):
        """Compare trusted receipt scope, never authorize an old claim."""
        return (isinstance(binding, dict) and set(binding) == set(self.binding())
                and type(binding.get('number')) is int and binding['number'] > 0
                and {**binding, 'number': self.number} == self.binding())


class Board:
    """Private controller API. Workers submit decisions, never Run identities."""
    def __init__(self, project, *, guard=None):
        self.project = project
        self.guard = guard

    def current(self, task_id, run_id):
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            task = kb.get_task(conn, task_id)
            if not task or task.status != 'running' or task.current_run_id != run_id:
                raise ValueError('current claimed Hermes run required')
            event = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND run_id=? '
                                 'AND kind=? ORDER BY id DESC LIMIT 1', (task_id, run_id, 'claimed')).fetchone()
            if event is None:
                raise ValueError('native claim required')
            reviewing = json.loads(event[0]).get('source_status') == 'review'
            card = json.loads(task.body)
            author = task.assignee
            if reviewing:
                origin = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND kind=? '
                                      'ORDER BY id DESC LIMIT 1', (task_id, 'review_requested')).fetchone()
                if origin is None:
                    raise ValueError('review origin missing')
                author = json.loads(origin[0])['implementer']
                if task.assignee not in self.project.reviewers_for(author):
                    raise ValueError('reviewer outside independent matrix')
            elif card.get('kind')=='diagnostic':
                if (not self.project.technical_roles or card.get('stage') not in self.project.technical_roles
                        or task.assignee!=self.project.technical_roles[card['stage']]):
                    raise ValueError('controller-assigned technical role required')
            elif card.get('kind') in ('brief','plan'):
                role='product' if card['kind']=='brief' else 'lead'
                if not self.project.coordination_roles or task.assignee!=self.project.coordination_roles[role]:
                    raise ValueError('controller-assigned coordination role required')
            else:
                self.project.reviewer(author)
        if (card.get('version') != 1 or card.get('kind') not in ('tests', 'implementation', 'integration', 'diagnostic', 'brief', 'plan')
                or not isinstance(card.get('release'), str) or not card['release']):
            raise ValueError('versioned delivery card required')
        if card['kind']=='brief' and reviewing:
            raise ValueError('business approval is not an agent review')
        return Run(task_id, run_id, task.assignee, card['kind'], reviewing, author,
                   card['release'], digest(card))

    def ensure(self, run):
        if self.guard:self.guard()
        if self.current(run.task, run.number) != run:
            raise ValueError('assignment or contract changed')

    def closed_review(self, task_id):
        """Read completed native provenance; never grants tool/worker authority."""
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            task=kb.get_task(conn,task_id);row=kb.latest_run(conn,task_id)
            if not task or task.status!='done' or not row or row.outcome!='completed':
                raise ValueError('completed independent review required')
            claim=conn.execute("SELECT id,payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",
                               (task_id,row.id)).fetchone()
            complete=conn.execute("SELECT id FROM task_events WHERE task_id=? AND run_id=? AND kind='completed' ORDER BY id DESC LIMIT 1",
                                  (task_id,row.id)).fetchone()
            origin=conn.execute("SELECT e.payload,r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
                "WHERE e.task_id=? AND e.kind='review_requested' AND e.id<? ORDER BY e.id DESC LIMIT 1",
                (task_id,claim['id'] if claim else 0)).fetchone()
            if (not claim or not complete or complete['id']<=claim['id'] or not origin
                    or json.loads(claim['payload']).get('source_status')!='review'):
                raise ValueError('manual done or synthetic approval is not a native independent execution')
            author=json.loads(origin['payload']).get('implementer');body=json.loads(task.body)
            if row.profile!=task.assignee or row.profile not in self.project.reviewers_for(author):
                raise ValueError('completed review identity outside the matrix')
            run=Run(task_id,row.id,row.profile,body['kind'],True,author,body['release'],digest(body))
            return run,row.metadata or {},json.loads(origin['metadata'] or '{}')

    def workspace(self, run):
        self.ensure(run)
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            task = kb.get_task(conn, run.task)
        if task.workspace_kind != 'dir' or not task.workspace_path:
            raise ValueError('assigned directory workspace required by the initial adapter')
        path = Path(task.workspace_path)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('prepared absolute workspace required')
        return path.resolve()

    def criteria(self,run):
        """Read server-owned release criteria, never caller-provided coverage."""
        self.ensure(run);kb,kbc,_=native()
        with kbc.connect_closing() as conn:body=json.loads(kb.get_task(conn,run.task).body)
        criteria=body.get('criteria')
        if (not isinstance(body.get('release_plan'),str) or not isinstance(criteria,list) or not criteria
                or any(not isinstance(item,str) or not item for item in criteria) or len(set(criteria))!=len(criteria)):
            raise ValueError('current reviewed package criteria required')
        return tuple(criteria)

    def repair_input(self,run):
        self.ensure(run);kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            return json.loads(kb.get_task(conn,run.task).body).get('inputs',{}).get('repair_review')

    def input(self, run, name, *, review_handoff=False):
        self.ensure(run)
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            if review_handoff:
                row = conn.execute('SELECT r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id '
                    'WHERE e.task_id=? AND e.kind=? ORDER BY e.id DESC LIMIT 1',
                    (run.task, 'review_requested')).fetchone()
                values = json.loads(row[0]) if row and row[0] else {}
            else:
                values = json.loads(kb.get_task(conn, run.task).body).get('inputs', {})
        if not isinstance(values, dict) or not isinstance(values.get(name), str):
            raise ValueError('durable handoff input missing: '+name)
        value = values[name]
        if value.startswith('parent:'):
            _, parent_id, key = value.split(':', 2)
            with kbc.connect_closing() as conn:
                link = conn.execute('SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?',
                                    (parent_id, run.task)).fetchone()
                parent = kb.get_task(conn, parent_id)
                if not link or not parent or parent.status != 'done':
                    raise ValueError('direct completed parent required')
                row = conn.execute('SELECT id,outcome,metadata FROM task_runs WHERE task_id=? '
                                   'ORDER BY id DESC LIMIT 1', (parent_id,)).fetchone()
                event = conn.execute('SELECT 1 FROM task_events WHERE task_id=? AND run_id=? AND kind=?',
                                     (parent_id, row['id'] if row else None, 'completed')).fetchone()
                if not row or row['outcome'] != 'completed' or not event:
                    raise ValueError('completed parent handoff missing')
                data = json.loads(row['metadata']) if row['metadata'] else {}
                value = data.get(key)
        if not isinstance(value, str) or value.startswith('parent:'):
            raise ValueError('resolved handoff evidence required')
        return value

    def review(self, run, summary, evidence, *, exclude=()):
        self.ensure(run)
        if run.reviewing:
            raise ValueError('implementation handoff required')
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            if not kb.request_review(conn, run.task, reviewer=self.project.reviewer(run.author, exclude=exclude),
                    summary=summary, metadata=evidence, expected_run_id=run.number):
                raise ValueError('native review handoff refused')

    def review_feedback(self,run,store):
        """Bounded cross-run memory: exact findings, not just an opaque hash."""
        self.ensure(run)
        kinds={'tests':('review','test_review'),'implementation':('review','delivery_review'),
               'plan':('plan_review','plan_review')}
        if run.kind not in kinds:return []
        field,receipt_kind=kinds[run.kind]
        _,kbc,_=native();result=[]
        with kbc.connect_closing() as conn:
            rows=conn.execute("SELECT run_id,payload FROM task_events WHERE task_id=? AND kind='changes_requested' ORDER BY id DESC LIMIT 2",
                (run.task,)).fetchall()
        for row in reversed(rows):
            payload=json.loads(row['payload']);reason=payload.get('reason')
            try:details=json.loads(reason)
            except (ValueError,TypeError):continue  # An older plain operator comment is not a receipt.
            evidence=details.get('evidence') if isinstance(details,dict) else None
            key=evidence.get(field) if isinstance(evidence,dict) else None
            if not key:continue
            record=store.receipt(key,kind=receipt_kind)
            scope,data=record['binding'],record['payload']
            if (scope.get('task')!=run.task or scope.get('contract')!=run.contract or scope.get('release')!=run.release
                    or scope.get('number')!=row['run_id'] or scope.get('author')!=run.author
                    or scope.get('kind')!=run.kind or scope.get('reviewing') is not True
                    or scope.get('actor') not in self.project.reviewers_for(run.author)
                    or data.get('project')!=self.project.fingerprint() or data['verdict']['decision']!='changes'):
                raise ValueError('review feedback belongs to another contract, role or execution')
            item=dict(receipt=key,reviewer=scope['actor'],run=scope['number'],verdict=data['verdict'])
            if run.kind=='plan':
                proposed=store.receipt(data['plan'],kind='work_plan')
                if (not replace(run,actor=run.author,reviewing=False).same_subject(proposed['binding'])
                        or proposed['binding']['number']>=scope['number']
                        or proposed['payload']['project']!=self.project.fingerprint()
                        or proposed['payload']['approval']!=self.input(run,'approved_brief')):
                    raise ValueError('plan feedback must match its author and current approved brief')
                item['plan']=data['plan']
            else:
                store.tree(data['snapshot']);item['snapshot']=data['snapshot']
            result.append(item)
        return result

    def escalate_review(self,run,receipt):
        self.ensure(run)
        if not run.reviewing:raise ValueError('only the current independent reviewer can escalate a review')
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            reason=json.dumps(dict(category='review_escalation',escalation=receipt))
            # Specialist input is distinct from an author's capability failure.
            # Preserve native recurrence protection for repeated review impasses.
            if not kb.block_task(conn,run.task,reason=reason,kind='needs_input',expected_run_id=run.number):
                raise ValueError('native technical review block refused')

    def require_parent(self, run, task_id):
        self.ensure(run)
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            link = conn.execute('SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?',
                                (task_id, run.task)).fetchone()
            task = kb.get_task(conn, task_id)
            if not link or not task or task.status != 'done':
                raise ValueError('completed delivery must be a direct dependency')

    def finish_review(self, run, summary, evidence, *, changes=False):
        self.ensure(run)
        if not run.reviewing:
            raise ValueError('independent review run required')
        kb, kbc, _ = native()
        with kbc.connect_closing() as conn:
            if changes:
                reason = json.dumps(dict(summary=summary, evidence=evidence), sort_keys=True)
                ok, _ = kb.request_changes(conn, run.task, reason=reason, expected_run_id=run.number)
            else:
                ok = kb.complete_task(conn, run.task, summary=summary, metadata=evidence,
                                       expected_run_id=run.number)
            if not ok:
                raise ValueError('native review transition refused')
