"""GitHub effect simulator backed by a local bare Git remote. Never a real CI."""
from unittest.mock import patch


class FakeGitHub:
    def __init__(self, repo, *, native=False, assignee='lead'):
        if not repo.project.qualification or not repo.local:
            raise ValueError('isolated local qualification repository required')
        self.repo, self.native, self.assignee = repo, native, assignee
        self.pr = None
        self.calls = dict(create=0, merge=0)
        self.api_calls = 0
        self.lose_create = self.lose_merge = False
        self.tree_override = None
        self.ok = True

    def find(self, branch):
        return self.pr

    def view(self, url):
        return dict(self.pr)

    def create(self, branch, title, body):
        self.calls['create'] += 1
        self.pr = dict(url=self.repo.project.repository+'/pull/1', state='OPEN',
            headRefOid=self.repo.remote_head(branch), headRefName=branch,
            baseRefName=self.repo.project.branch, baseRefOid=self.repo.base(), mergeCommit=None)
        if self.lose_create:
            raise TimeoutError('accepted; acknowledgement lost')
        return dict(self.pr)

    def accept(self, url, sha=None):
        if self.native:
            from fabriquinha.publication import GitHub
            with patch('hermes_cli.kanban_pr_acceptance._api', self.api):
                return GitHub(self.repo.project, self.assignee).accept(url, sha)
        sha = sha or self.pr['headRefOid']
        return dict(ok=self.ok, classification='success' if self.ok else 'pending', head_sha=sha,
                    required=[dict(context='tests', app_id=None)], checks=[dict(head_sha=sha)])

    def api(self, endpoint, **kwargs):
        self.api_calls += 1
        head, branch = self.pr['headRefOid'], self.repo.project.branch
        if endpoint == 'graphql':
            return {'data':{'repository':{'pullRequest':dict(headRefOid=head, baseRefName=branch,
                state=self.pr['state'], baseRef={'branchProtectionRule':{'requiredStatusChecks':[
                    dict(context='tests', app=None)]}})}}}
        if '/rules/branches/' in endpoint:
            return [[]]
        if '/check-runs?' in endpoint:
            commit = endpoint.split('/commits/')[1].split('/')[0]
            return [dict(total_count=1, check_runs=[dict(id=1, name='tests', app={'id':1},
                head_sha=commit, status='completed' if self.ok else 'in_progress',
                conclusion='success' if self.ok else None)])]
        if '/statuses?' in endpoint:
            return [[]]
        if '/pulls/' in endpoint:
            return dict(head={'sha':head}, base={'ref':branch}, state='open' if self.pr['state']=='OPEN' else 'closed',
                        merged=self.pr['state']=='MERGED')
        raise AssertionError(endpoint)

    def merge(self, url, head):
        self.calls['merge'] += 1
        assert head == self.pr['headRefOid']
        tree = self.tree_override or self.repo.git('rev-parse', head+'^{tree}').decode().strip()
        env = {**self.repo.env, 'GIT_AUTHOR_NAME':'GitHub fixture', 'GIT_AUTHOR_EMAIL':'fixture@example.invalid',
               'GIT_COMMITTER_NAME':'GitHub fixture', 'GIT_COMMITTER_EMAIL':'fixture@example.invalid'}
        sha = self.repo.git('commit-tree', tree, '-p', self.pr['baseRefOid'], '-p', head,
                            data=b'Fixture merge\n', env=env).decode().strip()
        self.repo.git('push', 'origin', sha+':refs/heads/'+self.repo.project.branch)
        self.pr.update(state='MERGED', mergeCommit={'oid':sha})
        if self.lose_merge:
            raise TimeoutError('merged; acknowledgement lost')
        return dict(self.pr)
