"""Authenticate a current Hermes run at the controller edge; no extra board DB."""
from dataclasses import dataclass, asdict
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
    def __init__(self, project):
        self.project = project

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
            author = task.assignee
            if reviewing:
                origin = conn.execute('SELECT payload FROM task_events WHERE task_id=? AND kind=? '
                                      'ORDER BY id DESC LIMIT 1', (task_id, 'review_requested')).fetchone()
                if origin is None:
                    raise ValueError('review origin missing')
                author = json.loads(origin[0])['implementer']
                if task.assignee not in self.project.reviewers_for(author):
                    raise ValueError('reviewer outside independent matrix')
            else:
                self.project.reviewer(author)
        card = json.loads(task.body)
        if (card.get('version') != 1 or card.get('kind') not in ('tests', 'implementation', 'integration')
                or not isinstance(card.get('release'), str) or not card['release']):
            raise ValueError('versioned delivery card required')
        return Run(task_id, run_id, task.assignee, card['kind'], reviewing, author,
                   card['release'], digest(card))

    def ensure(self, run):
        if self.current(run.task, run.number) != run:
            raise ValueError('assignment or contract changed')

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
