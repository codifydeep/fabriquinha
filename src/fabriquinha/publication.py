"""Controller-only Git/PR effects; Hermes remains the task lifecycle owner.

Check matching adapts Hermes (c) 2025 Nous Research, MIT; see THIRD_PARTY_NOTICES.md.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import time
from .artifacts import EXCLUDED, digest
from .effects import Journal, Pending, EffectBlocked, write_json


def sha(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{40}', value):
        raise ValueError('exact Git SHA required')
    return value


class Repository:
    """Bare controller checkout: no hooks, filters, product execution or force push."""
    def __init__(self, project, store, *, remote=None, assignee=None):
        self.project, self.store = project, store
        self.local = remote is not None
        if self.local and (not project.qualification or not Path(remote).resolve().is_dir()):
            raise ValueError('local remote override requires an isolated qualification')
        self.remote = str(Path(remote).resolve()) if self.local else project.repository
        self.path = store.root/'repository.git'
        environment = os.environ
        if not self.local:
            if not assignee:
                raise ValueError('explicit publisher profile identity required')
            from hermes_cli.kanban_pr_acceptance import _assignee_profile_home, _gh_env
            environment = _gh_env(_assignee_profile_home(assignee))
        self.env = {k:v for k,v in environment.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                        GIT_TERMINAL_PROMPT='0', GIT_ALLOW_PROTOCOL='file' if self.local else 'https')
        if not self.path.exists():
            self.path.mkdir(mode=0o700)
            self.git('init', '--bare', '--object-format=sha1')
            self.git('remote', 'add', 'origin', self.remote)
        if self.git('config', '--get', 'remote.origin.url').decode().strip() != self.remote:
            raise ValueError('private repository origin drift')
        if self.git('rev-parse', '--is-bare-repository').strip() != b'true':
            raise ValueError('controller-owned bare repository required')

    def git(self, *args, data=None, env=None):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.attributesFile=/dev/null',
            '-c', 'commit.gpgsign=false', '-c', 'maintenance.auto=false',
            '-c', 'credential.helper=!gh auth git-credential', '-C', str(self.path), *args],
            input=data, env=env or self.env, capture_output=True, check=True, timeout=45).stdout

    def base(self):
        self.git('fetch', '--no-tags', 'origin', 'refs/heads/'+self.project.branch)
        return sha(self.git('rev-parse', 'FETCH_HEAD').decode().strip())

    def remote_head(self, branch):
        rows = self.git('ls-remote', '--refs', 'origin', 'refs/heads/'+branch).decode().splitlines()
        if not rows:
            return None
        if len(rows) != 1 or rows[0].split()[1] != 'refs/heads/'+branch:
            raise ValueError('ambiguous remote branch')
        return sha(rows[0].split()[0])

    def snapshot(self, commit):
        commit = sha(commit)
        self.git('fetch', '--no-tags', 'origin', commit)
        folder = self.store.root.parent/'git-exports'/commit
        # An interrupted export is rebuilt from immutable Git objects, never author work.
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        total, expected = 0, set()
        for entry in filter(None, self.git('ls-tree', '-r', '-l', '-z', commit).split(b'\0')):
            header, raw_path = entry.split(b'\t', 1)
            mode, kind, oid, size = header.decode().split()
            name = raw_path.decode()
            path = PurePosixPath(name)
            if (mode not in {'100644','100755'} or kind != 'blob' or path.is_absolute()
                    or '..' in path.parts or any(p in EXCLUDED for p in path.parts)
                    or any(ord(c) < 32 for c in name) or path.name.startswith('.env') and path.name != '.env.example'):
                raise ValueError('unsupported or private tracked artifact')
            total += int(size)
            if int(size) > 16*1024*1024 or total > 128*1024*1024:
                raise ValueError('bounded Git export required')
            target = folder/name
            if target.is_symlink():
                raise ValueError('private export symlink rejected')
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(self.git('cat-file', 'blob', oid))
            target.chmod(0o700 if mode == '100755' else 0o600)
            expected.add(name)
        actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
        if actual != expected:
            raise ValueError('private Git export contains unexpected files')
        return self.store.capture(folder)

    def propose(self, snapshot, base, branch, actor, *, create=True):
        ref = 'refs/heads/'+branch
        existing = self.git('for-each-ref', '--format=%(objectname)', ref).decode().strip()
        if existing:
            parent = self.git('rev-parse', existing+'^').decode().strip()
            # Local-only objects need not be advertised by the remote yet.
            if parent != base or self._manifest(existing) != self.store.manifest(snapshot):
                raise ValueError('existing proposal is not the reviewed tree/base')
            return sha(existing)
        if not create:
            return None
        source = self.store.tree(snapshot)
        with tempfile.TemporaryDirectory(dir=self.store.root) as temporary:
            env = {**self.env, 'GIT_INDEX_FILE':str(Path(temporary)/'index'),
                'GIT_AUTHOR_NAME':actor, 'GIT_AUTHOR_EMAIL':actor+'@fabriquinha.invalid',
                'GIT_COMMITTER_NAME':'Fabriquinha', 'GIT_COMMITTER_EMAIL':'controller@fabriquinha.invalid'}
            self.git('read-tree', '--empty', env=env)
            for name, info in self.store.manifest(snapshot).items():
                blob = self.git('hash-object', '-w', '--stdin', data=(source/name).read_bytes()).decode().strip()
                self.git('update-index', '--add', '--cacheinfo', '100755' if info['executable'] else '100644', blob, name, env=env)
            tree = self.git('write-tree', env=env).decode().strip()
            head = self.git('commit-tree', tree, '-p', sha(base), data=('Reviewed delivery '+snapshot+'\n').encode(), env=env).decode().strip()
            self.git('update-ref', ref, sha(head), '0'*40)
        return head

    def _manifest(self, commit):
        result = {}
        for entry in filter(None, self.git('ls-tree', '-r', '-z', sha(commit)).split(b'\0')):
            header, raw_path = entry.split(b'\t', 1)
            mode, kind, oid = header.decode().split()
            if mode not in {'100644','100755'} or kind != 'blob':
                raise ValueError('regular reviewed files required')
            data = self.git('cat-file', 'blob', oid)
            result[raw_path.decode()] = dict(sha256=hashlib.sha256(data).hexdigest(),
                                            bytes=len(data), executable=mode == '100755')
        return result

    def push(self, branch, head):
        if self.project.qualification and not self.local:
            raise ValueError('qualification cannot push to GitHub')
        self.git('push', 'origin', sha(head)+':refs/heads/'+branch)
        return {'head':head}


class GitHub:
    """Fixed gh operations. No arbitrary endpoint, command or protection override."""
    FIELDS = 'url,state,headRefOid,headRefName,baseRefName,baseRefOid,mergeCommit'

    def __init__(self, project, assignee):
        self.project, self.assignee = project, assignee
        self.repo = project.repository.removeprefix('https://github.com/')

    def cli(self, *args, data=None):
        from hermes_cli.kanban_pr_acceptance import _assignee_profile_home, _gh_env
        env = _gh_env(_assignee_profile_home(self.assignee))
        return subprocess.run(['gh', *args], input=data, text=True, capture_output=True,
                              check=True, timeout=45, env=env).stdout

    def url(self, value):
        if not isinstance(value, str) or not re.fullmatch(re.escape(self.project.repository)+r'/pull/[1-9][0-9]*', value):
            raise ValueError('exact project PR required')
        return value

    def find(self, branch):
        rows = json.loads(self.cli('pr', 'list', '--repo', self.repo, '--head', branch,
            '--base', self.project.branch, '--state', 'all', '--json', self.FIELDS))
        if len(rows) > 1:
            raise ValueError('ambiguous publication PR')
        return rows[0] if rows else None

    def view(self, url):
        return json.loads(self.cli('pr', 'view', self.url(url), '--json', self.FIELDS))

    def writable(self):
        if self.project.qualification:
            raise ValueError('synthetic qualification cannot mutate real GitHub')

    def create(self, branch, title, body):
        self.writable()
        url = self.cli('pr', 'create', '--repo', self.repo, '--base', self.project.branch,
            '--head', branch, '--title', title, '--body-file', '-', data=body).strip()
        return self.view(url)

    def accept(self, url, commit=None):
        from hermes_cli.kanban_pr_acceptance import collect_acceptance, _api, _classify, _assignee_profile_home
        gate = collect_acceptance(self.repo, self.url(url), assignee=self.assignee)
        if commit is None or not gate['ok']:
            return gate
        commit = sha(commit)
        profile_home = _assignee_profile_home(self.assignee)
        pages = _api(f'repos/{self.repo}/commits/{commit}/check-runs?per_page=100&filter=latest',
                     paginate=True, profile_home=profile_home)
        runs = [r for page in pages for r in page['check_runs']]
        if len({r['id'] for r in runs}) != pages[0]['total_count']:
            raise ValueError('incomplete integrated check-run pagination')
        statuses = [{**s, 'sha':commit} for page in _api(
            f'repos/{self.repo}/commits/{commit}/statuses?per_page=100', paginate=True,
            profile_home=profile_home) for s in page]
        checks, outcomes = [], []
        for required in gate['required']:
            context, app = required['context'], required['app_id']
            matching = [r for r in runs if r['name'] == context and (app in (None,-1) or r['app']['id'] == app)]
            legacy = [s for s in statuses if s['context'] == context] if app in (None,-1) else []
            matching += [max(legacy, key=lambda s:s['id'])] if legacy else []
            if not matching:
                outcomes.append('missing')
                checks.append(dict(name=context, classification='missing', head_sha=commit))
            for check in matching:
                is_run = 'conclusion' in check
                outcome = check.get('conclusion') if is_run else check['state']
                classification = _classify(check, commit, outcome, is_run)
                outcomes.append(classification)
                checks.append(dict(name=context, id=check['id'], classification=classification,
                    head_sha=check.get('head_sha',check.get('sha')), conclusion=outcome))
        classification = next((v for v in outcomes if v != 'success'), 'success' if outcomes else 'missing')
        return {**gate, 'source_pr_head_sha':gate['head_sha'], 'head_sha':commit, 'checks':checks,
                'ok':classification == 'success', 'classification':classification}

    def merge(self, url, head):
        self.writable()
        self.cli('pr', 'merge', self.url(url), '--merge', '--match-head-commit', sha(head))
        return self.view(url)


class Publication:
    def __init__(self, project, store, board, repo, github):
        self.project, self.store, self.board, self.repo, self.github = project, store, board, repo, github
        self.journal = Journal(store.root/'effects')

    def require_ci(self, gate, head, deadline):
        if gate.get('head_sha') not in (None,head) or gate.get('classification') in {'failure','stale','auth'}:
            raise EffectBlocked('required CI failed or belongs to another identity: '+str(gate.get('classification')))
        if not gate.get('ok') or gate.get('head_sha') != head or not gate.get('required'):
            if time.time() >= deadline:
                raise EffectBlocked('required CI remained unavailable past its persistent deadline')
            raise Pending('required GitHub checks for the exact commit are not green')

    def publish(self, run, review_id):
        self.board.ensure(run)
        if run.kind != 'integration' or run.reviewing or self.board.input(run, 'delivery') != review_id:
            raise ValueError('current integration handoff required')
        review = self.store.receipt(review_id, kind='delivery_review')
        data, author = review['payload'], review['binding']
        self.board.require_parent(run, author['task'])
        if (data['project'] != self.project.fingerprint() or author['release'] != run.release
                or data['verdict']['decision'] != 'approve' or data['verdict']['findings']
                or self.project.reviewer(author['author']) != author['actor']):
            raise ValueError('independent approval of this exact project/release required')
        snapshot = data['snapshot']
        self.store.tree(snapshot)
        key = digest(dict(run=run.binding(), review=review_id, project=self.project.fingerprint()))
        with self.journal.lock(key+':publication'):
            return self._publish(run, review_id, snapshot, key)

    def description(self, run, review_id, snapshot):
        review = self.store.receipt(review_id,kind='delivery_review')
        data = review['payload']
        green = self.store.receipt(data['green'],kind='green')['payload']
        frozen = self.store.receipt(green['freeze'],kind='tests_frozen')['payload']
        red = self.store.receipt(frozen['red'],kind='red')['payload']
        controls = self.store.receipt(data['controls'],kind='controls')['payload']
        if green['snapshot'] != snapshot or controls['green'] != data['green']:
            raise ValueError('PR evidence does not identify the reviewed delivery')
        return ('Implementation card: '+review['binding']['task']+'\nIntegration card: '+run.task+
            '\nAuthor: '+review['binding']['author']+'\nIndependent reviewer: '+review['binding']['actor']+
            '\nSnapshot: '+snapshot+'\nReview receipt: '+review_id+
            '\n\n## TDD evidence\nTrusted command: `python -B /opt/fabriquinha/suite.py`'+
            '\nDiscovery directory: '+self.project.tests_dir+'\nValidator image: '+self.project.validation_image+
            '\nPassing baseline job: '+red['baseline_job']+
            '\nRed job: '+red['red_job']+'\nNew failing behaviors: '+', '.join(red['new_cases'])+
            '\nFrozen tests: '+green['freeze']+'\nGreen job: '+green['job']+
            '\nComplete suite: '+str(len(green['cases']))+' cases'+
            '\nNegative control jobs: '+', '.join(controls['jobs'])+
            '\nIndependent revalidation job: '+data['validation_job']+
            '\n\n## Release limits\nMerge-commit validation, deploy, QA and rollback remain mandatory. '
            'This PR is not release homologation. Evidence hashes reference private controller receipts.\n')

    def _publish(self, run, review_id, snapshot, key):
        folder = self.store.root/'publication'/key
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        initial = folder/'inputs.json'
        if not initial.exists():
            write_json(initial, dict(base=self.repo.base(), branch='feat/fabriquinha-'+key[:20],
                                     checks_deadline=time.time()+900))
        inputs = json.loads(initial.read_bytes())
        base, branch = inputs['base'], inputs['branch']
        identity = dict(binding=run.binding(), project=self.project.fingerprint(), review=review_id,
                        snapshot=snapshot, base=base, branch=branch)
        body = self.description(run,review_id,snapshot)

        def effect(operation, send, observe):
            self.board.ensure(run)
            return self.journal.do(key+':'+operation, identity, send, observe)

        head = effect('proposal', lambda: self.repo.propose(snapshot, base, branch, run.actor),
            lambda: self.repo.propose(snapshot, base, branch, run.actor, create=False))
        effect('push', lambda: self.repo.push(branch, head),
               lambda: {'head':head} if self.repo.remote_head(branch) == head else None)
        pr = effect('pr', lambda: self.github.create(branch, 'Reviewed delivery '+run.task, body),
                    lambda: self.github.find(branch))
        current = self.github.view(pr['url'])
        if (current['headRefOid'] != head or current['headRefName'] != branch
                or current['baseRefName'] != self.project.branch or current['state'] not in {'OPEN','MERGED'}
                or current['state'] == 'OPEN' and current['baseRefOid'] != base):
            raise EffectBlocked('PR head/base/state diverged; rebase and independent review required')
        gate = self.github.accept(pr['url'])
        self.store.record('pr_acceptance', run.binding(), dict(project=self.project.fingerprint(),
                          review=review_id, qualification=self.project.qualification, acceptance=gate))
        self.require_ci(gate,head,inputs['checks_deadline'])

        def merged():
            value = self.github.view(pr['url'])
            if value['state'] == 'MERGED' and value['headRefOid'] == head:
                return {'sha':sha(value['mergeCommit']['oid'])}
            if value['state'] == 'CLOSED':
                raise EffectBlocked('PR closed without merge')
            return None

        def merge():
            if self.repo.remote_head(self.project.branch) != base:
                raise EffectBlocked('integration base advanced; rebase and review required')
            self.github.merge(pr['url'], head)
            return merged()

        result = effect('merge', merge, merged)
        self.board.ensure(run)
        return self.store.record('publication', run.binding(), dict(project=self.project.fingerprint(),
            qualification=self.project.qualification, review=review_id, snapshot=snapshot, pr=pr['url'],
            base_sha=base, head_sha=head, merge_sha=result['sha'], delivery_approval=False))

    def validate_integrated(self, run, publication_id, quality):
        self.board.ensure(run)
        publication = self.store.receipt(publication_id, kind='publication')
        data = publication['payload']
        if (publication['binding'] != run.binding() or data['project'] != self.project.fingerprint()
                or self.board.input(run,'delivery') != data['review']):
            raise ValueError('current exact publication required')
        commit = sha(data['merge_sha'])
        if self.repo.remote_head(self.project.branch) != commit:
            raise EffectBlocked('integration branch advanced; qualify the new candidate')
        wait = self.store.root/'publication'/('integrated-'+publication_id+'.json')
        if not wait.exists():
            write_json(wait,dict(deadline=time.time()+900))
        gate = self.github.accept(data['pr'], commit)
        self.require_ci(gate,commit,json.loads(wait.read_bytes())['deadline'])
        snapshot = self.repo.snapshot(commit)
        if snapshot != data['snapshot']:
            raise EffectBlocked('merge changed reviewed content; independent review required')
        review = self.store.receipt(data['review'], kind='delivery_review')['payload']
        green = self.store.receipt(review['green'], kind='green')['payload']
        job, report = quality.observe(run, snapshot, 'integrated')
        if report['failures'] or set(report['cases']) != set(green['cases']):
            raise ValueError('integrated candidate must pass the complete frozen suite')
        self.board.ensure(run)
        if self.repo.remote_head(self.project.branch) != commit:
            raise EffectBlocked('integration branch changed during validation')
        return self.store.record('integrated', run.binding(), dict(project=self.project.fingerprint(),
            qualification=self.project.qualification, publication=publication_id, snapshot=snapshot,
            commit=commit, ci=gate, suite_job=job, delivery_approval=False))
