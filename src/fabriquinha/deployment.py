"""Fixed Python-HTTP build, Compose rollout/rollback and independent browser QA."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
from .artifacts import digest, files
from .browser import contract, load_contract
from .effects import Journal, Pending, EffectBlocked, write_json
from .executor import ROOT, docker
from .publication import sha
from .config import pool_subnets


class BrowserValidationFailed(ValueError):
    """Keep the actual negative job available to technical recovery."""
    def __init__(self,job,report):
        self.browser_job=job
        errors=report.get('errors',[]) if isinstance(report,dict) else []
        super().__init__('Independent deployed browser QA rejected; job '+job+': '+json.dumps(errors[:3])[:1500]+
                         '. A passing unittest SPIKE does not replace this browser result.')


def _network(project,suffix):
    """Observe only the exact, already reserved deployment network."""
    group=project.namespace+'-homologation';name=group+'_'+suffix
    ids=docker('network','ls','-q','--filter','name=^'+name+'$').split()
    if not ids:return None
    if len(ids)!=1:raise EffectBlocked('ambiguous deployment network; preserve it')
    info=json.loads(docker('network','inspect',ids[0]))[0]
    labels=info.get('Labels') or {}
    if (info['Name']!=name or info['Driver']!='bridge' or info['Scope']!='local'
            or info['Internal'] is not (suffix=='qa') or info.get('Ingress')
            or labels.get('com.docker.compose.project')!=group
            or labels.get('com.docker.compose.network')!=suffix
            or labels.get('fabriquinha.project')!=project.fingerprint()):
        raise EffectBlocked('deployment network ownership or policy mismatch; preserve it')
    expected=pool_subnets(project.network_pool).get(suffix)
    if expected and [item.get('Subnet') for item in (info.get('IPAM',{}).get('Config') or [])]!=[expected]:
        raise EffectBlocked('deployment network subnet drift; preserve it')
    return dict(id=info['Id'],name=name,internal=info['Internal'])


def deployment_networks(project):
    result=[_network(project,suffix) for suffix in ('default','qa')]
    if any(value is None for value in result):
        raise EffectBlocked('reserve both deployment networks before paid dispatch')
    return result


def network_identity(project,suffix):
    identity=dict(project=project.fingerprint(),group=project.namespace+'-homologation',suffix=suffix,version=1)
    subnet=pool_subnets(project.network_pool).get(suffix)
    if subnet:identity.update(version=2,subnet=subnet)
    return identity


def check_pool(project):
    planned=pool_subnets(project.network_pool)
    if not planned:return
    ranges={**planned,'reserved':str(list(ipaddress.IPv4Network(project.network_pool).subnets(new_prefix=28))[3])}
    # Check both owned names before the first creation, including policy drift
    # outside the proposed range. Never adopt a foreign or replaced network.
    for suffix in ('default','qa'):_network(project,suffix)
    ids=docker('network','ls','-q').split()
    if len(ids)>4096:raise EffectBlocked('network inventory exceeds qualified local scope')
    values=json.loads(docker('network','inspect',*ids)) if ids else []
    for info in values:
        for item in (info.get('IPAM',{}).get('Config') or []):
            try:existing=ipaddress.ip_network(item['Subnet'],strict=True)
            except (ValueError,KeyError,TypeError):raise EffectBlocked('network subnet observation invalid; preserve existing networks') from None
            if existing.version!=4:continue
            for suffix,subnet in ranges.items():
                if not existing.overlaps(ipaddress.IPv4Network(subnet)):continue
                if suffix in ('default','qa') and info['Name']==project.namespace+'-homologation_'+suffix:
                    continue  # Exact ownership and subnet were checked above.
                labels=info.get('Labels') or {}
                if (suffix=='core' and info['Name']==project.namespace+'_default' and str(existing)==subnet
                        and info.get('Driver')=='bridge' and info.get('Scope')=='local' and not info.get('Ingress')
                        and info.get('Internal') is False and labels.get('com.docker.compose.project')==project.namespace
                        and labels.get('com.docker.compose.network')=='default' and labels.get('fabriquinha.project')==project.fingerprint()):
                    continue
                raise EffectBlocked('configured network pool overlaps another Docker network; choose an unused pool before preparation')


def prepare_networks(project,store):
    """Explicit paused-install operation, no prune or uncertain-create retry."""
    journal=Journal(store.root/'effects');group=project.namespace+'-homologation'
    check_pool(project)
    for suffix in ('default','qa'):
        def observe():return _network(project,suffix)
        observe()  # Reject foreign ownership before recording any creation intent.
        identity=network_identity(project,suffix)
        def send():
            # Revalidate after the journal lock; never replace a foreign network.
            current=observe()
            if current is not None:return current
            args=['network','create','--driver','bridge']
            for key,value in (('com.docker.compose.project',group),('com.docker.compose.network',suffix),
                              ('fabriquinha.project',project.fingerprint())):
                args+=['--label',key+'='+value]
            if suffix=='qa':args+=['--internal']
            if identity.get('subnet'):args+=['--subnet',identity['subnet']]
            docker(*args,group+'_'+suffix)
            return observe()
        journal.do('deployment-network:'+suffix,identity,send,observe)
    # Recheck reality even when a previous journaled creation was acknowledged.
    return deployment_networks(project)


def web_spec(project,artifact,effect):
    if (artifact['project']!=project.fingerprint()
            or not re.fullmatch(r'sha256:[a-f0-9]{64}',artifact['image'])):
        raise ValueError('owned content-addressed image required')
    sha(artifact['commit'])
    networks={'default':dict(driver='bridge'),'qa':dict(internal=True)}
    if project.delivery_roles and not project.qualification:
        networks={suffix:dict(external=True,name=project.namespace+'-homologation_'+suffix)
                  for suffix in ('default','qa')}
    return dict(services={'web':dict(image=artifact['image'],pull_policy='never',
        user='65534:65534',read_only=True,cap_drop=['ALL'],security_opt=['no-new-privileges:true'],
        tmpfs=['/tmp:rw,noexec,nosuid,size=32m'],mem_limit='256m',cpus=1,pids_limit=128,
        ports=[dict(target=8080,host_ip='127.0.0.1',protocol='tcp')],networks=['default','qa'],
        labels={'delivery-kit.lifecycle':'homologation','fabriquinha.project':project.fingerprint(),
                'fabriquinha.artifact':artifact['receipt'],'fabriquinha.effect':effect},
        logging=dict(driver='json-file',options={'max-size':'1m','max-file':'2'}),
        healthcheck=dict(test=['CMD','python','-c',
            'import urllib.request; assert urllib.request.urlopen("http://127.0.0.1:8080/health",timeout=2).status==200'],
            interval='2s',timeout='3s',retries=5,start_period='1s'),restart='unless-stopped')},
        networks=networks)


class Deployment:
    def __init__(self,project,store,board,runner):
        self.project,self.store,self.board,self.runner=project,store,board,runner
        self.journal=Journal(store.root/'effects')
        self.group=project.namespace+'-homologation'

    def current(self,run,*,review=False):
        self.board.ensure(run)
        if run.kind!='integration' or run.reviewing is not review or review and run.actor==run.author:
            raise ValueError('current independent QA or integration owner required')

    def _command(self,folder,name,*args,timeout):
        try:
            result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def text(value):return value.decode(errors='replace') if isinstance(value,bytes) else value or ''
            write_json(folder/(name+'.json'),dict(timeout=True,stdout=text(error.stdout)[:1024*1024],
                                                stderr=text(error.stderr)[:1024*1024]))
            raise
        write_json(folder/(name+'.json'),dict(returncode=result.returncode,
            stdout=result.stdout[:1024*1024],stderr=result.stderr[:1024*1024]))
        result.check_returncode()
        return result.stdout

    def integrated(self,run,integrated_id,repository):
        self.current(run)
        record=self.store.receipt(integrated_id,kind='integrated')
        data=record['payload']
        publication=self.store.receipt(data['publication'],kind='publication')
        published=publication['payload']
        if (not run.same_subject(record['binding']) or data['project']!=self.project.fingerprint()
                or not data['ci']['ok'] or data['ci']['head_sha']!=data['commit']
                or not run.same_subject(publication['binding'])
                or published['project']!=self.project.fingerprint()
                or published['merge_sha']!=data['commit'] or published['snapshot']!=data['snapshot']
                or self.board.input(run,'delivery')!=published['review']):
            raise ValueError('current independently validated integrated candidate required')
        if repository.remote_head(self.project.branch)!=data['commit']:
            raise EffectBlocked('integration branch advanced; qualify the new candidate')
        return data,published['review']

    def artifact(self,run,integrated_id,repository,*,baseline=False):
        data,review_id=self.integrated(run,integrated_id,repository)
        commit,snapshot,role=data['commit'],data['snapshot'],'candidate'
        if baseline:
            pub=self.store.receipt(data['publication'],kind='publication')['payload']
            review=self.store.receipt(pub['review'],kind='delivery_review')['payload']
            green=self.store.receipt(review['green'],kind='green')['payload']
            frozen=self.store.receipt(green['freeze'],kind='tests_frozen')['payload']
            from .quality import Quality
            red=Quality(self.project,self.store,None,self.board).test_evidence(frozen['red'])['payload']
            job=self.store.receipt(red['baseline_job'],kind='suite_job')['payload']
            commit,snapshot,role=pub['base_sha'],red['baseline'],'bootstrap'
            report=job['report']
            if (job['identity']['snapshot']!=snapshot or job['exit_code']!=0 or report['tests_run']<1
                    or any(report[k] for k in ('failures','errors','skips','expected_failures','unexpected_successes'))
                    or repository.snapshot(commit)!=snapshot):
                raise ValueError('passing exact Git baseline required for bootstrap rollback')
        else:
            from .executor import browser_contract
            from .browser import expected_checks
            expected_checks(self.store.tree(snapshot)/self.project.tests_dir,browser_contract(self.project,self.store))
        recipe=ROOT/'Dockerfile.web'
        scope=dict(subject=run.subject(),project=self.project.fingerprint(),review=review_id,
                      commit=sha(commit),snapshot=snapshot,role=role,recipe=hashlib.sha256(recipe.read_bytes()).hexdigest())
        key=digest(scope)
        with self.journal.lock(key+':artifact'):
            return self._build(run,integrated_id,scope,key)

    def _build(self,run,integrated_id,scope,key):
        source=self.store.tree(scope['snapshot'])
        snapshot,commit=scope['snapshot'],scope['commit']
        recipe=ROOT/'Dockerfile.web'
        folder=self.store.root/'builds'/key
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        inputs=folder/'inputs.json'
        if not inputs.exists():write_json(inputs,dict(tag=self.project.namespace+'-app:'+str(time.time_ns()),
                                                     origin=run.binding(),integrated=integrated_id))
        initial=json.loads(inputs.read_bytes())
        tag=initial['tag']
        identity={**scope,'binding':initial['origin'],'integrated':initial['integrated']}
        product=folder/'context/product';product.mkdir(mode=0o700,parents=True,exist_ok=True)
        for relative in self.store.manifest(snapshot):
            target=product/relative;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if not target.exists():os.link(source/relative,target)
        if files(product)!=self.store.manifest(snapshot):
            raise EffectBlocked('build context differs from the exact reviewed snapshot')
        def observe():
            try:info=json.loads(docker('image','inspect',tag))[0]
            except subprocess.CalledProcessError:return None
            cfg=info['Config'];labels=cfg.get('Labels',{})
            if (cfg.get('User')!='65534:65534' or cfg.get('Volumes')
                    or cfg.get('Entrypoint')!=['python','-B','/app/app.py','8080']
                    or labels.get('fabriquinha.build')!=key or labels.get('fabriquinha.snapshot')!=snapshot
                    or labels.get('org.opencontainers.image.revision')!=commit):
                raise EffectBlocked('built image policy or identity mismatch')
            return dict(image=info['Id'],tag=tag)
        def build():
            self.board.ensure(run)
            if hashlib.sha256(recipe.read_bytes()).hexdigest()!=scope['recipe']:
                raise EffectBlocked('canonical build recipe changed during execution')
            self._command(folder,'build-output','build','--network=none','--pull=false','-f',str(recipe),
                '--build-arg','SOURCE_SHA='+commit,'--label','fabriquinha.build='+key,
                '--label','fabriquinha.snapshot='+snapshot,'--label','org.opencontainers.image.revision='+commit,
                '-t',tag,str(product.parent),timeout=90)
            return observe()
        image=self.journal.do(key+':build',identity,build,observe)
        self.board.ensure(run)
        return self.store.record('artifact',initial['origin'],{**identity,**image,'qualification':self.project.qualification})

    def read_artifact(self,key):
        value=self.store.receipt(key,kind='artifact')['payload']
        if value['project']!=self.project.fingerprint():raise ValueError('foreign artifact')
        return {**value,'receipt':key}

    def service(self,artifact=None,*,effect=None):
        ids=docker('ps','-aq','--filter','label=com.docker.compose.project='+self.group,
                   '--filter','label=com.docker.compose.service=web').split()
        if not ids:return None
        if len(ids)!=1:raise EffectBlocked('ambiguous owned web deployment')
        info=json.loads(docker('inspect',ids[0]))[0]
        host,cfg=info['HostConfig'],info['Config'];labels=cfg.get('Labels',{})
        if (labels.get('fabriquinha.project')!=self.project.fingerprint()
                or labels.get('delivery-kit.lifecycle')!='homologation'
                or cfg.get('User')!='65534:65534' or not host.get('ReadonlyRootfs')
                or host.get('Privileged') or host.get('CapAdd') or 'ALL' not in (host.get('CapDrop') or [])
                or any(m['Type']!='tmpfs' for m in info.get('Mounts',[]))):
            raise EffectBlocked('existing deployment is not the owned fixed sandbox')
        owned=self.read_artifact(labels.get('fabriquinha.artifact'))
        if info['Image']!=owned['image'] or set(info['NetworkSettings']['Networks'])!={self.group+'_default',self.group+'_qa'}:
            raise EffectBlocked('existing deployment image/network identity mismatch')
        if artifact and (info['Image']!=artifact['image'] or labels.get('fabriquinha.artifact')!=artifact['receipt']):return None
        if effect and labels.get('fabriquinha.effect')!=effect:return None
        healthy=info['State']['Running'] and info['State'].get('Health',{}).get('Status')=='healthy'
        ports=info['NetworkSettings']['Ports'].get('8080/tcp') or []
        if ports and (len(ports)!=1 or ports[0]['HostIp']!='127.0.0.1' or not ports[0]['HostPort'].isdigit()):
            raise EffectBlocked('local published service port required')
        return dict(container=info['Id'],image=info['Image'],artifact=labels['fabriquinha.artifact'],
                    url='http://127.0.0.1:'+ports[0]['HostPort'] if ports else None,healthy=bool(healthy and ports),
                    network=self.group+'_qa')

    def continuity_observation(self,history):
        """Join safe live identity to accepted QA; never infer from names/ports."""
        current=self.service();prior=None
        if history:
            accepted=self.store.receipt(history['acceptance'],kind='release_acceptance')['payload']
            qa=self.store.receipt(accepted['final_qa'],kind='release_evidence')['payload']
            artifact=self.read_artifact(qa['artifact'])
            if (accepted['project']!=self.project.fingerprint() or qa['project']!=accepted['project']
                    or accepted['state']!='HOMOLOGADA' or artifact['role']!='candidate'
                    or any(qa[key]!=accepted[key] or artifact[key]!=accepted[key] for key in ('commit','image'))):
                raise ValueError('historical deployment must match exact acceptance and QA')
            prior=dict(acceptance=history['acceptance'],qa=accepted['final_qa'],artifact=qa['artifact'],
                commit=artifact['commit'],image=artifact['image'],snapshot=artifact['snapshot'])
        return dict(current=current,previous_homologated_deployment=prior,
            current_is_previous_homologation=bool(current and prior and current['artifact']==prior['artifact'] and current['image']==prior['image']),
            policy='The exact previous same-project homologation may be replaced by the fixed candidate/rollback/restore sequence. Preserve every unmatched deployment. The incident error describes a historical attempt; classify current identity by these receipts, not that error wording. Resume still requires actual integration and independent deployed QA.',
            delivery_approval=False)

    def _up(self,run,artifact,operation):
        self.current(run)
        if self.project.delivery_roles and not self.project.qualification:deployment_networks(self.project)
        scope=dict(subject=run.subject(),artifact=artifact['receipt'],operation=operation,
                      policy=digest(web_spec(self.project,artifact,'pending')))
        key=digest(scope);folder=self.store.root/'deployments'/key
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        inputs=folder/'inputs.json'
        if not inputs.exists():write_json(inputs,dict(origin=run.binding()))
        origin=json.loads(inputs.read_bytes())['origin']
        identity={**scope,'binding':origin}
        compose=folder/'compose.json'
        write_json(compose,web_spec(self.project,artifact,key))
        def observe():
            value=self.service(artifact,effect=key)
            return value if value and value['healthy'] else None
        def send():
            self.board.ensure(run)
            for suffix,internal in (('default',False),('qa',True)):
                network=docker('network','ls','-q','--filter','name=^'+self.group+'_'+suffix+'$').strip()
                if network:
                    net=json.loads(docker('network','inspect',network))[0]
                    if net['Internal'] is not internal or net.get('Labels',{}).get('com.docker.compose.project')!=self.group:
                        raise EffectBlocked('unknown deployment network must be preserved')
            old=self.service()
            if old:
                write_json(folder/'previous.json',old)
                write_json(folder/'previous-logs.json',dict(output=docker('logs',old['container'])[:1024*1024]))
            self._command(folder,'compose-output','compose','-p',self.group,'-f',str(compose),
                          'up','-d','--no-deps','--pull','never','web',timeout=60)
            return observe()
        current=self.journal.do(key+':compose',identity,send,observe)
        self.board.ensure(run)
        return self.store.record('deployment',origin,{**identity,**current})

    def rollout(self,run,candidate_id,previous_id,repository):
        self.current(run)
        candidate,previous=self.read_artifact(candidate_id),self.read_artifact(previous_id)
        if (not run.same_subject(self.store.receipt(candidate_id)['binding'])
                or candidate['role']!='candidate' or candidate['image']==previous['image']):
            raise ValueError('distinct candidate and rollback artifacts required')
        integrated,_=self.integrated(run,candidate['integrated'],repository)
        if integrated['commit']!=candidate['commit'] or integrated['snapshot']!=candidate['snapshot']:
            raise ValueError('artifact must match its integrated result')
        with self.journal.lock('rollout:'+self.group):
            current=self.service()
            if current and current['artifact'] not in (candidate_id,previous_id):
                raise EffectBlocked('unrelated current deployment must be preserved')
            steps=[]
            if current is None or previous['role']=='bootstrap':steps.append(self._up(run,previous,'bootstrap'))
            for artifact,operation in ((candidate,'candidate'),(previous,'rollback'),(candidate,'restore')):
                if operation!='rollback':self.integrated(run,candidate['integrated'],repository)
                steps.append(self._up(run,artifact,operation))
            final=self.service(candidate)
            if not final or not final['healthy']:raise EffectBlocked('restored candidate is not the healthy current image')
            self.board.ensure(run)
            self.integrated(run,candidate['integrated'],repository)
            return self.store.record('rollout',run.binding(),dict(project=self.project.fingerprint(),
                qualification=self.project.qualification,candidate=candidate_id,previous=previous_id,
                steps=steps,final=final,delivery_approval=False))

    def qa(self,run,rollout_id,repository):
        self.current(run,review=True)
        if self.board.input(run,'rollout',review_handoff=True)!=rollout_id:
            raise ValueError('exact current QA handoff required')
        rollout=self.store.receipt(rollout_id,kind='rollout')
        data=rollout['payload']
        if (data['project']!=self.project.fingerprint() or rollout['binding']['actor']!=run.author
                or rollout['binding']['task']!=run.task or rollout['binding']['contract']!=run.contract):
            raise ValueError('independent QA of this rollout required')
        artifact=self.read_artifact(data['candidate'])
        if self.board.input(run,'delivery')!=artifact['review']:
            raise ValueError('deployed QA must retain the current approved delivery')
        if repository.remote_head(self.project.branch)!=artifact['commit']:
            raise EffectBlocked('integration branch advanced before deployed QA')
        from .board import Run
        owner=Run(**rollout['binding'])
        steps=[self.store.receipt(key,kind='deployment') for key in data['steps']]
        if (not owner.same_subject(self.store.receipt(data['candidate'])['binding'])
                or len(steps)<3 or any(not owner.same_subject(step['binding']) or not step['payload']['healthy'] for step in steps)
                or [s['payload']['operation'] for s in steps[-3:]]!=['candidate','rollback','restore']
                or steps[-2]['payload']['artifact']!=data['previous']
                or steps[-1]['payload']['artifact']!=data['candidate']):
            raise ValueError('actual rollback and restoration evidence required')
        before=self.service(artifact)
        if not before or not before['healthy'] or before['container']!=data['final']['container']:
            raise EffectBlocked('deployment changed before QA')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        for path,expected_value in (('/health',{'status':'ok'}),('/identity',{'source_sha':artifact['commit']})):
            with opener.open(before['url']+path,timeout=5) as response:
                if response.status!=200 or json.loads(response.read(4097))!=expected_value:
                    raise ValueError('CEO local URL identity/health mismatch')
        from .executor import browser_contract
        from .browser import expected_checks,acceptance_manifest
        mode=browser_contract(self.project,self.store)
        folder=self.store.tree(artifact['snapshot'])/self.project.tests_dir
        expected=expected_checks(folder,mode)
        job=self.runner.browser(run,artifact['snapshot'],artifact['commit'])
        evidence=self.store.receipt(job,kind='browser_job')
        value=evidence['payload'];report=value['report']
        if (evidence['binding']!=run.binding() or value['exit_code']!=0 or value['infrastructure_error']
                or value['identity']['snapshot']!=artifact['snapshot'] or value['identity']['commit']!=artifact['commit']
                or not isinstance(report,dict) or report.get('status')!='passed' or report.get('source_sha')!=artifact['commit']
                or report.get('checks')!=expected or report.get('errors')
                or not value['screenshot_sha256']):
            raise BrowserValidationFailed(job,report)
        checks=report['checks']
        if mode==2:
            from .quality import Quality,preview_evidence,suite_report
            manifest=acceptance_manifest(folder)
            if value['identity'].get('browser_contract')!=2 or report.get('cases')!=manifest['cases']:
                raise ValueError('exact deployed acceptance inventory required')
            integrated=self.store.receipt(artifact['integrated'],kind='integrated')
            suite=self.store.receipt(integrated['payload']['suite_job'],kind='suite_job')
            identity=suite['payload']['identity']
            if (suite['binding']!=integrated['binding'] or identity['binding']!=integrated['binding']
                    or identity['project']!=self.project.fingerprint() or identity['snapshot']!=artifact['snapshot']
                    or identity['phase']!='integrated' or integrated['payload']['commit']!=artifact['commit']):
                raise ValueError('exact integrated suite required for acceptance gates')
            preview_evidence(self.project,self.store,suite['payload'],artifact['snapshot'],'integrated')
            facts=suite_report(suite['payload'])
            review=self.store.receipt(artifact['review'],kind='delivery_review')['payload']
            green=self.store.receipt(review['green'],kind='green')['payload']
            quality=Quality(self.project,self.store,None,self.board)
            frozen=quality.frozen_plan(self.store.receipt(green['freeze'],kind='tests_frozen'))
            if facts['failures'] or set(facts['cases'])!=set(frozen['cases']):raise ValueError('complete independently frozen suite required')
            quality.protect(frozen['baseline'],artifact['snapshot'])
            if quality.tests(artifact['snapshot'])!=frozen['tests']:raise ValueError('deployed tests differ from independent freeze')
            checks=list(manifest['criteria'])
        after=self.service(artifact)
        if after!=before:raise EffectBlocked('deployment changed during QA')
        if repository.remote_head(self.project.branch)!=artifact['commit']:
            raise EffectBlocked('integration branch advanced during deployed QA')
        self.board.ensure(run)
        return self.store.record('release_evidence',run.binding(),dict(project=self.project.fingerprint(),
            qualification=self.project.qualification,rollout=rollout_id,artifact=data['candidate'],
            integrated=artifact['integrated'],commit=artifact['commit'],image=artifact['image'],
            url=after['url'],container=after['container'],qa_job=job,checks=checks,
            rollback_verified=True,delivery_approval=False))
