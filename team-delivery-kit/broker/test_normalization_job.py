"""Controller-only fixed job, with durable backup separate from worker workspace."""
import hashlib,json,time


def run(broker,issue,scope,source,selection):
    base=broker.issue_base(issue)
    work=broker.PREFIX+'-work-'+hashlib.sha256(scope.encode()).hexdigest()[:32]
    actual=broker.docker('GET','/volumes/'+work)
    if not actual or actual.get('Labels',{}).get('delivery-kit.scope')!=scope or actual['Labels'].get('delivery-kit.owner')!=broker.OWNER:
        raise ValueError('normalization workspace identity drift')
    volume=broker.PREFIX+'-format-backup-'+source
    labels={'delivery-kit.owner':broker.OWNER,'delivery-kit.format-source':source}
    old=broker.docker('GET','/volumes/'+volume)
    if old is None:broker.docker('POST','/volumes/create',{'Name':volume,'Labels':labels})
    elif any(old.get('Labels',{}).get(k)!=v for k,v in labels.items()):raise ValueError('normalization backup identity drift')
    job=broker.PREFIX+'-normalize-'+source
    prior=broker.docker('GET','/containers/'+job+'/json')
    if prior:
        if prior['State']['Running'] or any(prior['Config'].get('Labels',{}).get(k)!=v for k,v in labels.items()):
            raise ValueError('normalization job identity or activity drift')
        broker.docker('DELETE','/containers/'+prior['Id'])
    broker.docker('POST','/containers/create?name='+job,{'Image':broker.IMAGE,'User':'10000:10000',
        'Entrypoint':['python'],'Cmd':['/normalize_new_test.py'],'NetworkDisabled':True,
        'Env':['NORMALIZE_SELECTION='+json.dumps(selection)],'Labels':labels,
        'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','CapDrop':['ALL'],
            'SecurityOpt':['no-new-privileges'],'Memory':134217728,'PidsLimit':16,
            'Mounts':[{'Type':'volume','Source':base['volume'],'Target':'/base','ReadOnly':True},
                      {'Type':'volume','Source':work,'Target':'/workspace'},
                      {'Type':'volume','Source':volume,'Target':'/snapshot'}]}})
    try:
        broker.docker('POST','/containers/'+job+'/start');deadline=time.time()+20
        while time.time()<deadline:
            status=broker.docker('GET','/containers/'+job+'/json')['State']
            if not status['Running']:
                if status['ExitCode']:raise ValueError('fixed normalization rejected')
                return {**json.loads(broker.docker_stdout(job)),'backup_volume':volume,'worker_image':broker.IMAGE}
            time.sleep(.2)
        raise ValueError('normalization deadline')
    finally:
        info=broker.docker('GET','/containers/'+job+'/json')
        if info and all(info['Config'].get('Labels',{}).get(k)==v for k,v in labels.items()):
            broker.docker('DELETE','/containers/'+info['Id']+'?force=true')
