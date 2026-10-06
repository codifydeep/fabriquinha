"""Controller-only, evaluation-scoped read-only evidence attachment; no verdict."""
import hashlib
import json
import time

import broker as b
import handoffs

SOURCE = '01a107ac-fb88-728b-b6e3-592e1fde3821'
EXPECTED_TEST_HASH = '7f725f75a7fcbc6a24752399f19f130d1ae519c554f8185077372c286fb7cd77'
EXPECTED_OUTPUT = '8e4c1d7581a15edb21b9d8214bbc9f907d71278cc0275d65651b456fdbb4d335'
FINDINGS = [
    'tests/test_incremental_u3.py:493-499,643: beta is issued before gamma; '
    'genAIdx > genBIdx is asserted true despite append-only request recording.',
    'tests/test_incremental_u3.py:292,431,455-464,631: deferral is enabled and never '
    'consumed; create follow-up GET remains held, but the new row is asserted rendered.',
    'tests/test_incremental_u3.py:299-302,457,631: POST stub hardcodes title posted '
    'instead of reading the submitted alpha new; the assertion expects alpha new.',
    'tests/test_incremental_u3.py:314,493-509,517-526: pending.shift resolves FIFO '
    'while the driver claims current-first then stale query/status resolution.'
]
PROBE = r'''
import hashlib,json
from pathlib import Path
root=Path('/delivery')
manifest=json.loads((root/'manifest.json').read_bytes())['files']
for path,item in manifest.items():
    file=root/path
    assert not file.is_symlink() and file.is_file()
    assert hashlib.sha256(file.read_bytes()).hexdigest()==item['sha256']
paths=['tests/test_incremental_u3.py','app/static/app.js','app/static/index.html']
test=(root/paths[0]).read_text()
for fragment in ["out.genA_newer = genAIdx > genBIdx;", "const held = pending.shift();",
                 "items.push({ id: id, title: 'posted', completed: false });",
                 "out.rendered_after_create = renderedTitles();"]:
    assert fragment in test
mutations=[line.strip() for line in test.splitlines() if 'deferred.' in line]
assert mutations==['if (deferred.length) {']+['deferred.push(true);']*4
print(json.dumps({'file_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest()
                               for p in paths},
                  'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest()}))
'''

with b.LOCK, b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    row = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (SOURCE,)).fetchone()
    data = json.loads(row['data'])
    assert row['stage'] == 'budget_paused' and not data.get('harness_diagnosis')
    failure = data['validation_failure']
    assert failure['category'] == 'executed_test_failure' and failure['output_sha256'] == EXPECTED_OUTPUT
    output = con.execute('SELECT output FROM frozen_suite_failures WHERE task_id=? AND output_sha256=?',
                         (SOURCE, EXPECTED_OUTPUT)).fetchone()[0]
    assert hashlib.sha256(output.encode()).hexdigest() == EXPECTED_OUTPUT
    assert con.execute("SELECT 1 FROM snapshots WHERE task_id=? AND volume=? AND status='complete'",
                       (SOURCE, failure['volume'])).fetchone()
    backup = b.STATE/'u3-before-harness-diagnosis-20261004.sqlite'
    assert not backup.exists()
    import sqlite3
    with sqlite3.connect(backup) as target:
        con.backup(target)
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    route = json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',
                                  (row['issue_id'],)).fetchone()[0])

name = b.PREFIX+'-harness-inspection-'+SOURCE
assert not b.docker('GET', '/containers/'+name+'/json')
image = b.docker('GET', '/images/delivery-kit-execution-broker:20261004.95/json')['Id']
labels = {'delivery-kit.owner': b.OWNER, 'delivery-kit.source-task': SOURCE,
          'com.docker.compose.project': b.PREFIX}
created = b.docker('POST', '/containers/create?name='+name, dict(
    Image=image, User='10000:10000', Entrypoint=['python'], Cmd=['-c', PROBE],
    NetworkDisabled=True, Labels=labels,
    HostConfig=dict(ReadonlyRootfs=True, NetworkMode='none', CapDrop=['ALL'],
                    SecurityOpt=['no-new-privileges'], Memory=268435456, PidsLimit=64,
                    Mounts=[dict(Type='volume', Source=failure['volume'], Target='/delivery', ReadOnly=True)])))
assert created and created.get('Id')
try:
    b.docker('POST', '/containers/'+name+'/start')
    deadline = time.time()+30
    while time.time() < deadline:
        info = b.docker('GET', '/containers/'+name+'/json')
        if info and not info['State']['Running']:
            assert info['State']['ExitCode'] == 0
            proof = json.loads(b.docker_stdout(name, limit=8192))
            break
        time.sleep(.2)
    else:
        raise ValueError('harness inspection deadline')
finally:
    info = b.docker('GET', '/containers/'+name+'/json')
    if info and all(info['Config']['Labels'].get(k) == v for k,v in labels.items()):
        b.docker('DELETE', '/containers/'+name+'?force=true')
assert proof['file_sha256']['tests/test_incremental_u3.py'] == EXPECTED_TEST_HASH
proof.update(source_task=SOURCE, output_sha256=EXPECTED_OUTPUT, approval=False, findings=FINDINGS)
with b.LOCK, b.db() as con:
    current = con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?', (SOURCE,)).fetchone()
    assert current['data'] == row['data'] and current['stage'] == 'budget_paused'
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    data['harness_diagnosis'] = proof
    data['resume_stage'] = 'diagnose_cto'
    data['diagnostic_revision'] = hashlib.sha256(json.dumps(proof, sort_keys=True).encode()).hexdigest()+':harness-facts-v1'
    note = handoffs.harness_diagnosis_instruction(data, route)
    handoffs.save(con, SOURCE, row['issue_id'], 'budget_paused', 'budget', data, time.time())
print(json.dumps({'status':'attached_not_dispatched','instruction_chars':len(note),
                  'backup_sha256':hashlib.sha256(backup.read_bytes()).hexdigest(),
                  'findings':len(FINDINGS),'approval':False}))
