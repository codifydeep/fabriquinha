"""Controller preflight for one compilation retry after an installed code change.

Never resets cards, counters, approvals or planning. No model calls or dispatch.
"""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
ACTIVE_LEASE_QUERY = "SELECT count(*) FROM leases WHERE status IN ('creating','running','closing')"


def active_lease_count(con):
    return con.execute(ACTIVE_LEASE_QUERY).fetchone()[0]


def qualified_revision(config, private):
    from materialize_plan import plan_from_ledger
    from qa_postmerge_trial import digest
    from start_eval import cli
    from evalctl import PROJECT
    if PROJECT != 'delivery-kit-port2':
        raise ValueError('compilation recovery restricted to isolated installation')
    def read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
            raise ValueError('bounded compilation recovery evidence required')
        return json.loads(path.read_text())
    state = read(Path(private) / 'planning-intake' / (config['name'] + '.json'))
    mapped = read(Path(private) / 'planned-cards' / (config['name'] + '.json'))
    if (state.get('stage') != 'plan_ready'
            or state.get('configuration_sha256') != config['selection']['configuration_sha256']
            or state.get('base_sha') != config['selection']['base_sha']
            or mapped.get('plan_sha256') != digest(plan_from_ledger(state))
            or set(mapped.get('cards', {})) != {'C1', 'C2'}):
        raise ValueError('current immutable plan required for compilation recovery')
    for issue in mapped['cards'].values():
        record = cli('get', issue)
        if record.get('status') != 'blocked' or record.get('assignee_id') is not None:
            raise ValueError('unassigned blocked cards required for compilation recovery')
    installed = json.loads(subprocess.check_output(['docker', 'exec', '-i',
        PROJECT + '-execution-broker-1', 'python', '-c',
        'import hashlib,json,sqlite3; from pathlib import Path; '
        'c=sqlite3.connect("file:/broker-state/leases.sqlite?mode=ro",uri=True); '
        'print(json.dumps(dict(active=c.execute(' + repr(ACTIVE_LEASE_QUERY) + ').fetchone()[0], '
        'hashes={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in '
        '["/broker.py","/execution_context.py","/handoff_runtime.py"]})))'], text=True))
    sources = {'/broker.py': 'broker/server.py', '/execution_context.py': 'execution_context.py',
               '/handoff_runtime.py': 'broker/handoff_runtime.py'}
    expected = {path: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for path, name in sources.items()}
    if installed.get('active') != 0 or installed.get('hashes') != expected:
        raise ValueError('idle installed context protection must match validated source')
    return digest(dict(input=config['sha256'], plan=mapped['plan_sha256'], installed=expected,
                       preflight=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       compiler=hashlib.sha256((ROOT / 'planned_delivery.py').read_bytes()).hexdigest()))
