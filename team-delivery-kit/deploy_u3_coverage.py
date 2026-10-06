"""Operator-owned exact-SHA deployment/QA probe, not release or feature admission."""
import json
import hashlib
import re
import sys
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import integrate_u3_coverage as integration
import portable_browser_qa as browser
from docker_grouping import args as grouping
from release_eval import save_receipt

pub=integration.publication
PORT=19448
NAME=pub.PROJECT+'-u3-coverage-qa'
ROLLBACK=pub.PROJECT+'-u3-coverage-rollback'
OWNER='u3-coverage-qualification-v1'
RECEIPT=pub.ROOT/'.local-port2/release-receipts/U3-COVERAGE-DEPLOYMENT.json'
BROWSER_IMAGE='sha256:72cb1ba338b9f4047a52a8fea4702ebebebc7eb9dac11aba9c1becf605c12b4b'


def docker(*args):return pub.run('docker',*args).decode().strip()


def inspect(name,kind='container'):
    result=subprocess.run(['docker',kind,'inspect',name],capture_output=True,text=True)
    if result.returncode:
        absent=('No such' in result.stderr or
                (kind=='network' and 'network '+name+' not found' in result.stderr))
        if absent:
            docker('info','--format','{{.ServerVersion}}')
            return None
        raise ValueError('Docker inspection unavailable')
    values=json.loads(result.stdout)
    if len(values)!=1:raise ValueError('one Docker identity required')
    return values[0]


def initial(merged):
    return dict(schema='u3-coverage-deployment-probe-v1',stage='deployment_intent',
        source_sha=merged['merged_sha'],previous_sha=integration.review.BASE,
        integration_review_sha256=merged['final_review_sha256'],container=NAME,
        url='http://127.0.0.1:'+str(PORT),operator_invoked=True,
        historical_tdd_red=False,product_admission_authorized=False,release_homologated=False,
        model_calls=0)


def can_begin(saved):return saved is None


def identity(data,image,sha):
    host=data.get('HostConfig',{});config=data.get('Config',{});labels=config.get('Labels',{})
    if (data.get('Image')!=image or config.get('User')!='10000:10000'
            or labels.get('delivery-kit.u3-coverage')!=OWNER or labels.get('delivery-kit.source-sha')!=sha
            or host.get('Privileged') or host.get('ReadonlyRootfs') is not True
            or host.get('Mounts') or host.get('Binds') or host.get('CapDrop')!=['ALL']
            or host.get('NetworkMode') not in ('bridge','default') or host.get('PidMode')=='host'
            or host.get('IpcMode')=='host' or host.get('Devices') or host.get('DeviceRequests')
            or 'no-new-privileges' not in host.get('SecurityOpt',[])
            or host.get('PortBindings',{}).get('8080/tcp')!=[{'HostIp':'127.0.0.1','HostPort':str(PORT)}]):
        raise ValueError('exact safe owned deployment identity required')


def build(sha):
    names=pub.tracked(pub.REPO,sha)
    selected=[p for p in names if p.startswith('app/') or p=='Dockerfile.feedback-bootstrap']
    if not selected or 'Dockerfile.feedback-bootstrap' not in selected:raise ValueError('fixed app build required')
    with tempfile.TemporaryDirectory(prefix='u3-coverage-build-') as tmp:
        root=Path(tmp)
        for path in selected:
            target=root/path;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(pub.git(pub.REPO,'cat-file','blob',names[path][1]))
        tag=pub.PROJECT+'-u3-coverage:'+sha[:12]
        docker('build','--pull=false','--network','none','-f',str(root/'Dockerfile.feedback-bootstrap'),
               '--build-arg','SOURCE_SHA='+sha,'-t',tag,str(root))
    data=inspect(tag,'image')
    if data['Config'].get('Labels',{}).get('delivery-kit.source-sha')!=sha:raise ValueError('built SHA label mismatch')
    return data['Id']


def start(name,image,sha):
    if inspect(name):raise ValueError('existing container retained; inspect instead of overwrite')
    docker('run','-d','--name',name,*grouping('u3-coverage',namespace=pub.PROJECT,kind='homologation'),
        '--label','delivery-kit.u3-coverage='+OWNER,'--label','delivery-kit.source-sha='+sha,
        '--publish','127.0.0.1:'+str(PORT)+':8080','--read-only','--user','10000:10000',
        '--tmpfs','/tmp:rw,nosuid,nodev,size=16m','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','128m','--cpus','0.5','--pids-limit','64','--restart','no',
        '--env','FEEDBACK_DB_PATH=/tmp/feedback.db',image)
    data=inspect(name);identity(data,image,sha)
    return data['Id']


def http_checks(sha):
    checks=[]
    for path,payload in (('/health',{'status':'ok','source_sha':sha}),
                         ('/ready',{'status':'ready','source_sha':sha})):
        with urllib.request.urlopen('http://127.0.0.1:'+str(PORT)+path,timeout=3) as response:
            if response.status!=200 or json.load(response)!=payload:raise ValueError('exact health/readiness SHA required')
        checks.append(path)
    for path,kind in (('/','text/html'),('/static/app.js','application/javascript'),('/static/style.css','text/css')):
        with urllib.request.urlopen('http://127.0.0.1:'+str(PORT)+path,timeout=3) as response:
            if response.status!=200 or not response.headers['Content-Type'].startswith(kind) or not response.read(65537):
                raise ValueError('deployed static MIME or content failed')
        checks.append(path)
    return checks


def ready(sha):
    for _ in range(30):
        try:return http_checks(sha)
        except OSError:time.sleep(.2)
    raise ValueError('deployment startup deadline')


def remove_owned(kind,name,owner):
    data=inspect(name,kind)
    if data is None:return
    labels=data.get('Labels',{}) if kind=='network' else data.get('Config',{}).get('Labels',{})
    if labels.get('delivery-kit.browser-qa')!=owner:raise ValueError('cleanup ownership mismatch')
    if kind=='container' and data['State']['Running']:
        try:docker('stop','--time','3',data['Id'])
        except subprocess.TimeoutExpired:
            current=inspect(name,kind)
            if current is None:return
            if current['Id']!=data['Id'] or current['State']['Running']:raise
    try:docker(kind,'rm',data['Id'])
    except subprocess.TimeoutExpired:
        if inspect(name,kind) is not None:raise
        return
    if inspect(name,kind) is not None:raise ValueError('cleanup absence not verified')


def cleanup_evidence(proof,receipt,path):
    owner=proof.get('owner','');ident=proof.get('identity',{})
    expected=[['network',owner],['container',owner+'-app'],['container',owner+'-browser']]
    if (proof.get('status')!='failed' or proof.get('cleanup')!='failed'
            or not proof.get('error','').startswith(' cleanup: ')
            or proof.get('automated') is not True or not re.fullmatch(r'delivery-kit-browser-[a-f0-9]{32}',owner)
            or proof.get('resources')!=expected or proof.get('result',{}).get('status')!='passed'
            or proof['result'].get('source_sha')!=receipt.get('source_sha')
            or ident.get('source_sha')!=receipt.get('source_sha')
            or ident.get('application_image')!=receipt.get('image')
            or ident.get('deployed_container_id')!=receipt.get('container_id')
            or ident.get('config')!=receipt.get('browser_config')
            or ident.get('scenario_sha256')!=hashlib.sha256(browser.SCRIPT.read_bytes()).hexdigest()
            or ident.get('runtime_env')!={'FEEDBACK_DB_PATH':'/tmp/feedback.db'}):
        raise ValueError('only evidence-bound cleanup-only failure may resume')
    screenshot=path.with_suffix('.png')
    if screenshot.is_symlink() or hashlib.sha256(screenshot.read_bytes()).hexdigest()!=proof.get('screenshot_sha256'):
        raise ValueError('preserved screenshot mismatch')
    return expected


def rollback(receipt):
    receipt['stage']='rollback_intent';save_receipt(RECEIPT,receipt)
    identity(inspect(NAME),receipt['image'],receipt['source_sha'])
    docker('stop',NAME)
    try:
        start(ROLLBACK,receipt['rollback_image'],receipt['previous_sha'])
        receipt['rollback_http_checks']=ready(receipt['previous_sha'])
    finally:
        data=inspect(ROLLBACK)
        if data:
            identity(data,receipt['rollback_image'],receipt['previous_sha'])
            if data['State']['Running']:docker('stop',ROLLBACK)
            docker('rm',data['Id'])
        identity(inspect(NAME),receipt['image'],receipt['source_sha'])
        docker('start',NAME);ready(receipt['source_sha'])
    receipt.update(stage='technical_qualification_passed',rollback_verified=True,
        rollback_scope='isolated_temporary_database_slot_only',application_restored=True,
        independent_agent_qa_approval=False,next_action='Independent QA handoff and explicit release lifecycle reconciliation')
    if receipt.get('recovered_from'):
        receipt['recovered_incident_reason']=receipt.pop('reason','')
        receipt.pop('category',None);receipt.pop('owner',None)
    save_receipt(RECEIPT,receipt);print(json.dumps(receipt))


def resume_cleanup(receipt):
    if receipt.get('stage')!='blocked' or not receipt.get('reason','').startswith('post-deploy browser QA  cleanup: '):
        raise ValueError('explicit cleanup-only blocked probe required')
    identity(inspect(NAME),receipt['image'],receipt['source_sha']);ready(receipt['source_sha'])
    if inspect(ROLLBACK):raise ValueError('unexpected rollback resource retained')
    folder=pub.ROOT/'.local-port2/browser-acceptance/U3-COVERAGE'
    candidates=[p for p in folder.glob('*.json') if re.fullmatch(r'[a-f0-9]{64}\.json',p.name)]
    if len(candidates)!=1 or candidates[0].is_symlink():raise ValueError('unique regular browser evidence required')
    path=candidates[0];proof=json.loads(path.read_text());resources=cleanup_evidence(proof,receipt,path)
    history=RECEIPT.with_name('U3-COVERAGE-DEPLOYMENT-BLOCKED-CLEANUP.json')
    if not history.exists():save_receipt(history,receipt)
    for kind,name in reversed(resources):remove_owned(kind,name,proof['owner'])
    certificate=dict(schema='u3-browser-cleanup-recovery-v1',original_receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        screenshot_sha256=proof['screenshot_sha256'],owner=proof['owner'],resources_absent=resources,
        source_sha=receipt['source_sha'],release_homologated=False,model_calls=0)
    certpath=RECEIPT.with_name('U3-COVERAGE-CLEANUP-RECOVERY.json');save_receipt(certpath,certificate)
    receipt.update(browser_receipt=str(path),browser_sha256=pub.digest(proof),screenshot_sha256=proof['screenshot_sha256'],
        browser_checks=proof['result']['checks'],cleanup_certificate=str(certpath),cleanup_certificate_sha256=pub.digest(certificate),
        recovered_from=str(history))
    rollback(receipt)


def main():
    if RECEIPT.is_symlink():raise ValueError('regular deployment receipt required')
    merged=json.loads(integration.RECEIPT.read_text())
    final=integration.load_final()
    if (merged.get('stage')!='coverage_integrated' or merged.get('final_review')!=final
            or pub.remote_base(pub.REPO)!=merged.get('merged_sha')):
        raise ValueError('verified current coverage integration required')
    protection=integration.gates.api('branches/main/protection');integration.gates.protection_ok(protection)
    if pub.digest(protection)!=merged['protection_sha256']:raise ValueError('branch protection drift')
    integration.gates.exact_ci(integration.gates.api('commits/'+merged['merged_sha']+'/check-runs'),merged['merged_sha'])
    saved=json.loads(RECEIPT.read_text()) if RECEIPT.exists() else None
    if saved:
        if saved.get('source_sha')!=merged['merged_sha'] or saved.get('integration_review_sha256')!=merged['final_review_sha256']:
            raise ValueError('deployment receipt lineage drift')
        if sys.argv[1:]==['--resume-cleanup']:
            resume_cleanup(saved);return
        if sys.argv[1:]:raise ValueError('unsupported operation')
        if saved['stage']!='technical_qualification_passed':
            raise ValueError('previous deployment probe unfinished/blocked; diagnose, do not repeat')
        identity(inspect(NAME),saved['image'],saved['source_sha']);ready(saved['source_sha'])
        if not Path(saved['browser_receipt']).is_file():raise ValueError('browser evidence missing')
        if saved.get('cleanup_certificate'):
            path=Path(saved['browser_receipt']);proof=json.loads(path.read_text())
            resources=cleanup_evidence(proof,saved,path)
            cert=json.loads(Path(saved['cleanup_certificate']).read_text())
            if (pub.digest(proof)!=saved['browser_sha256'] or pub.digest(cert)!=saved['cleanup_certificate_sha256']
                    or cert['original_receipt_sha256']!=hashlib.sha256(path.read_bytes()).hexdigest()
                    or cert['resources_absent']!=resources or any(inspect(name,kind) is not None for kind,name in resources)):
                raise ValueError('cleanup recovery evidence drift')
        else:
            browser.qualify(config=saved['browser_config'],deployed_container=NAME,source_sha=saved['source_sha'],
                evidence_dir=Path(saved['browser_receipt']).parent,runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
        print(json.dumps(saved));return
    if inspect(NAME) or inspect(ROLLBACK):raise ValueError('existing qualification containers retained')
    if subprocess.check_output(['docker','ps','--filter','publish='+str(PORT),'--format','{{.ID}}']).strip():
        raise ValueError('qualification port already occupied')
    receipt=initial(merged);save_receipt(RECEIPT,receipt)
    try:
        receipt.update(image=build(receipt['source_sha']),rollback_image=build(receipt['previous_sha']))
        save_receipt(RECEIPT,receipt)
        receipt['container_id']=start(NAME,receipt['image'],receipt['source_sha'])
        receipt['http_checks']=ready(receipt['source_sha'])
        config=dict(scenario='feedback-board-search-v1',browser_image=BROWSER_IMAGE)
        evidence_dir=pub.ROOT/'.local-port2/browser-acceptance/U3-COVERAGE'
        receipt.update(stage='browser_intent',browser_config=config);save_receipt(RECEIPT,receipt)
        old=os.environ.get('DELIVERY_KIT_COMPOSE_PROJECT')
        os.environ['DELIVERY_KIT_COMPOSE_PROJECT']=pub.PROJECT
        try:
            proof=browser.qualify(config=config,deployed_container=NAME,source_sha=receipt['source_sha'],
                evidence_dir=evidence_dir,runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
        finally:
            if old is None:os.environ.pop('DELIVERY_KIT_COMPOSE_PROJECT',None)
            else:os.environ['DELIVERY_KIT_COMPOSE_PROJECT']=old
        if proof['status']!='passed' or proof.get('cleanup')!='passed':raise ValueError('actual browser QA required')
        candidates=[p for p in evidence_dir.glob('*.json') if json.loads(p.read_text())==proof]
        if len(candidates)!=1:raise ValueError('unique durable browser receipt required')
        receipt.update(browser_receipt=str(candidates[0]),browser_sha256=pub.digest(proof),
            screenshot_sha256=proof['screenshot_sha256'],browser_checks=proof['result']['checks'],stage='rollback_intent')
        save_receipt(RECEIPT,receipt)
        identity(inspect(NAME),receipt['image'],receipt['source_sha'])
        docker('stop',NAME)
        try:
            start(ROLLBACK,receipt['rollback_image'],receipt['previous_sha'])
            receipt['rollback_http_checks']=ready(receipt['previous_sha'])
        finally:
            data=inspect(ROLLBACK)
            if data:
                identity(data,receipt['rollback_image'],receipt['previous_sha'])
                if data['State']['Running']:docker('stop',ROLLBACK)
                docker('rm',data['Id'])
            identity(inspect(NAME),receipt['image'],receipt['source_sha'])
            docker('start',NAME)
            ready(receipt['source_sha'])
        receipt.update(stage='technical_qualification_passed',rollback_verified=True,
            rollback_scope='isolated_temporary_database_slot_only',application_restored=True,
            independent_agent_qa_approval=False,next_action='Independent QA handoff and explicit release lifecycle reconciliation')
        save_receipt(RECEIPT,receipt);print(json.dumps(receipt))
    except Exception as error:
        receipt.update(stage='blocked',category=type(error).__name__,reason=str(error)[:300],owner='devops',
            next_action='Diagnose preserved probe; no identical retry or release success')
        save_receipt(RECEIPT,receipt);raise


if __name__=='__main__':main()
