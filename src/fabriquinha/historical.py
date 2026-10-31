"""Read-only validator provenance for a controller-accepted historical release.

This view cannot produce new jobs or receipts. New delivery still uses the live
installation; no worker-supplied validator pin is accepted.
"""
from .artifacts import Store


class AcceptedHistory(Store):
    def __init__(self,project,store,acceptance):
        record=store.receipt(acceptance,kind='release_acceptance');data=record['payload']
        graph=store.receipt(data['graph'],kind='release_graph')
        qa=store.receipt(data['final_qa'],kind='release_evidence')
        job=store.receipt(qa['payload']['qa_job'],kind='browser_job')['payload']
        bundle=graph['payload'].get('validation_bundle')
        if (record['binding'].get('actor')!='controller' or data['project']!=project.fingerprint()
                or data['state']!='HOMOLOGADA' or data.get('qualification') is not project.qualification
                or data.get('delivery_approval') is not (not project.qualification) or graph['binding']!=record['binding']
                or graph['payload']['project']!=data['project'] or not bundle
                or qa['binding']['release']!=record['binding']['release']
                or qa['payload']['commit']!=data['commit'] or qa['payload']['project']!=data['project']
                or job['identity'].get('validation_bundle')!=bundle or job['identity'].get('browser_contract')!=2
                or job['identity'].get('binding')!=qa['binding'] or job['exit_code']!=0
                or job['report']['status']!='passed' or job['report'].get('source_sha')!=data['commit']):
            raise ValueError('exact accepted historical validator provenance required')
        if set(store.manifest(bundle))!={'suite.py','browser.py'}:raise ValueError('historical bundle contents changed')
        store.tree(bundle)
        from .quality import CONTROL_CONTRACT
        self.root=store.root
        self.installation=dict(project=project.fingerprint(),validation_bundle=bundle,browser_contract=2,control_contract=CONTROL_CONTRACT)

    def capture(self,*args,**kwargs):raise ValueError('historical validation is read-only')
    def record(self,*args,**kwargs):raise ValueError('historical validation cannot approve new evidence')
    def checkout(self,*args,**kwargs):raise ValueError('historical validation cannot create workspaces')


def recover(runtime,value):
    """One authorized native resume after proving the historical read repair.

    No counter/body edits. A further failure remains subject to native triage.
    """
    import json
    from .artifacts import digest
    from .board import Run
    from .effects import write_json,EffectBlocked
    from .kanban_lane import native
    from .recovery import Recovery
    if not isinstance(value,dict) or set(value)!={'task','diagnosis'}:raise ValueError('exact task and CTO diagnosis required')
    if not runtime.control.read()['paused']:raise ValueError('paused repair required')
    r=runtime.releases;kb,api,_=native()
    with runtime.intake.lock(),api.connect_closing() as conn:
        if conn.execute('SELECT count(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]:raise ValueError('settle workers')
        task=kb.get_task(conn,value['task']);body=json.loads(task.body) if task else {}
        if body.get('kind')!='integration':raise ValueError('integration repair only')
        key=digest(['historical-validator-repair',value]);path=r.store.root/'operations'/(key+'.json')
        decision=r.store.receipt(value['diagnosis'],kind='diagnostic_decision');d=decision['payload'];scope=decision['binding']
        incident=r.store.receipt(d['incident'],kind='incident');source=incident['binding']
        diagnostic=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
        if (source['task']!=task.id or source['contract']!=digest(body) or source['reviewing'] is not False
                or scope['actor']!=r.project.technical_roles['cto'] or scope['release']!=body['release']
                or d['project']!=r.project.fingerprint() or d['action']!='hold' or not d.get('experiment')
                or not diagnostic or diagnostic.status!='done' or not closed or closed.id!=scope['number']
                or (closed.metadata or {}).get('diagnosis')!=value['diagnosis']
                or incident['payload']['failure']!='exact installed validation bundle required'):
            raise ValueError('exact historical-validator CTO hold required')
        latest=kb.latest_run(conn,task.id)
        if path.exists():
            result=json.loads(path.read_bytes());receipt=r.store.receipt(result['receipt'],kind='historical_validator_repair')
            if receipt['payload']['request']!=value or receipt['binding']!=source:raise ValueError('repair receipt drift')
            if latest.id!=source['number'] or task.status!='triage':return result
        else:
            if task.status!='triage' or not latest or latest.id!=source['number'] or not latest.ended_at:raise ValueError('exact settled integration triage required')
            if Recovery(r.project,r.store,r.board).expired_effects(task.id):raise EffectBlocked('settle source effects')
            anchor=kb.get_task(conn,body['release_anchor'])
            graph=r.store.receipt(json.loads(r.graph_path(anchor,body).read_bytes())['receipt'],kind='release_graph')['payload']
            if not graph.get('assisted'):raise ValueError('explicitly assisted graph required')
            item=next(i for i in graph['items'] if i['cards']['integration']['id']==task.id)
            for card in item['cards'].values():r.check_card(conn,card)
            delivery,review,_=r.closed(item['cards']['implementation']['id'],'delivery','delivery_review')
            if review['payload']['verdict']['decision']!='approve':raise ValueError('approved delivery required')
            seed=r.store.receipt(graph['seed'],kind='release_seed')['payload']
            rollback=r.accepted_rollback(body['release'],seed)
            if not rollback:raise ValueError('historical rollback proof required')
            receipt=r.store.record('historical_validator_repair',source,dict(project=r.project.fingerprint(),request=value,
                rollback=rollback,delivery=delivery,assisted=True,delivery_approval=False,
                authority='Owner authorized historical-validator compatibility repair; same integration and retained delivery'))
            result=dict(receipt=receipt,assisted=True,delivery_approval=False);write_json(path,result)
        if not kb.specify_triage_task(conn,task.id,author='controller'):raise ValueError('native triage transition refused')
        return result
