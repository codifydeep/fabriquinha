"""Controller-owned original-base suite receipt; never a fabricated review RPC."""
import json
import time
try:
    import incremental_checkpoints as ledger
    import incremental_evidence as evidence
except ImportError:
    from broker import incremental_checkpoints as ledger,incremental_evidence as evidence


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS initial_base_validations('
        'source_task TEXT PRIMARY KEY,manifest_sha256 TEXT,status TEXT,receipt TEXT)')


def capture(b,source):
    with b.LOCK,b.db() as con:
        initialize(con)
        row=con.execute('SELECT config,state FROM test_decompositions WHERE source_task=?',(source,)).fetchone()
        if not row or json.loads(row[1]).get('stage')!='proposal_ready':
            raise ValueError('accepted proposal required before initial base validation')
        config=json.loads(row[0]);base=b.issue_base(config['issue_id'])
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle qualification window required')
        prior=con.execute('SELECT manifest_sha256,status,receipt FROM initial_base_validations WHERE source_task=?',(source,)).fetchone()
        if prior:
            if prior[0]!=base['manifest_sha256']:raise ValueError('original base validation identity drift')
            if prior[1]!='passed':raise ValueError('initial validation interrupted or failed: diagnosis required')
            return json.loads(prior[2])
        con.execute('INSERT INTO initial_base_validations VALUES(?,?,?,?)',
                    (source,base['manifest_sha256'],'running','{}'));con.commit()
        name=b.PREFIX+'-initial-base-'+source
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.initial-base-source':source,
                'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'initial-base-validation'}
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=getattr(b,'OFFLINE_IMAGE',b.IMAGE),User='10000:10000',
                Entrypoint=['python3'],Cmd=['/initial_base_inspect.py'],NetworkDisabled=True,
                Env=['PYTHONDONTWRITEBYTECODE=1','EXPECTED_BASE_MANIFEST_SHA256='+base['manifest_sha256']],
                Labels=labels,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',
                    CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=96,
                    Mounts=[dict(Type='volume',Source=base['volume'],Target='/base',ReadOnly=True)])))
            b.docker('POST','/containers/'+name+'/start')
            deadline=time.time()+20
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']!=0:raise ValueError('original base inspection failed')
                    spec=json.loads(b.docker_stdout(name));break
                time.sleep(.1)
            else:raise TimeoutError('original base inspection deadline')
            if spec['manifest_sha256']!=base['manifest_sha256'] or spec['base_sha']!=base['base_sha']:
                raise ValueError('original base inspection identity mismatch')
            suite=b.run_portable_suite(base['volume'],source,spec,suite_evidence=True)
            proof=dict(executed_by='controller_original_base_suite',source_task=source,
                manifest_sha256=base['manifest_sha256'],base_sha=base['base_sha'],
                baseline_test_sha256=spec['baseline_test_sha256'],contract_sha256=spec['contract_sha256'],
                tests=suite['tests'],test_image=suite['test_image'],test_command=suite['test_command'],
                output_sha256=suite['output_sha256'],exit_code=0,network='none',snapshot_mount='readonly',
                suite_sha256=evidence.suite_digest(suite['test_image'],suite['test_command']))
            con.execute("UPDATE initial_base_validations SET status='passed',receipt=? WHERE source_task=?",
                        (json.dumps(proof,sort_keys=True),source));con.commit()
            return proof
        except Exception as error:
            con.execute("UPDATE initial_base_validations SET status='failed',receipt=? WHERE source_task=?",
                (json.dumps({'category':type(error).__name__,'owner':config['cto'],
                             'required_action':'diagnose_initial_base_validation'}),source));con.commit()
            raise
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config'].get('Labels',{}).get(k)==v for k,v in labels.items()):
                b.docker('DELETE','/containers/'+info['Id']+'?force=true')
