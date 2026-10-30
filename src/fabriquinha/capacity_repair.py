"""Operator-authorized additive validator repair before any delivery evidence.

Keep the failed graph immutable; materialize successors from the same reviewed
plan and baseline. Historical rejected source is evidence, never a test freeze.
"""
import importlib.util
import json
from pathlib import Path
from .artifacts import digest
from .effects import write_json,EffectBlocked
from .executor import seal_validation,validation_files
from .kanban_lane import native
from .recovery import Recovery


def inventory(file,folder):
    spec=importlib.util.spec_from_file_location('fixed_capacity_validator',file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.acceptance_manifest(folder)


def selection(r,anchor):
    path=r.folder(anchor)/'capacity-repair.json'
    if not path.exists():return None
    key=json.loads(path.read_bytes())['receipt'];record=r.store.receipt(key,kind='capacity_repair')
    data=record['payload']
    if record['binding']!=r.binding(anchor) or data['project']!=r.project.fingerprint():
        raise ValueError('capacity repair scope changed')
    installed=json.loads((r.store.root.parent/'installation.json').read_bytes())
    if installed!=data['after']:raise ValueError('finish paused capacity installation before dispatch')
    return key,data


def admit(runtime,value):
    if not isinstance(value,dict) or set(value)!={'release','diagnosis','rejected_snapshot','source_run'}:
        raise ValueError('exact release, diagnosis, rejected snapshot and historical source run required')
    if not runtime.control.read()['paused']:raise ValueError('paused installation required')
    r=runtime.releases;kb,api,_=native()
    with runtime.intake.lock(),api.connect_closing() as conn:
        if conn.execute('SELECT count(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]:raise ValueError('settle workers')
        anchor=kb.get_task(conn,value['release'])
        if not anchor or anchor.status!='blocked':raise ValueError('active release required')
        path=r.folder(anchor)/'capacity-repair.json'
        if path.exists():
            key=json.loads(path.read_bytes())['receipt'];record=r.store.receipt(key,kind='capacity_repair')
            data=record['payload'];current=json.loads((runtime.root/'installation.json').read_bytes())
            if record['binding']!=r.binding(anchor) or data['request']!=value or current not in (data['before'],data['after']):
                raise ValueError('capacity installation drift')
            write_json(runtime.root/'installation.json',data['after'])
            return dict(receipt=key,assisted=True,delivery_approval=False)
        spec=r.specification(conn,anchor)
        if not spec or spec.get('maintenance_replan'):raise ValueError('approved normal product plan required')
        prior=json.loads((r.folder(anchor)/'graph.json').read_bytes())['receipt']
        graph=r.store.receipt(prior,kind='release_graph')
        if graph['binding']!=r.binding(anchor) or graph['payload']['plan_review']!=spec['review']:raise ValueError('exact graph required')
        first=graph['payload']['items'][0]['cards']['tests'];source=r.check_card(conn,first);latest=kb.latest_run(conn,source.id)
        if source.status!='triage' or not latest or not latest.ended_at:raise ValueError('settled tests triage required')
        for item in graph['payload']['items']:
            for card in item['cards'].values():
                r.check_card(conn,card)
                if card['id']!=source.id and kb.latest_run(conn,card['id']):raise ValueError('downstream execution forbids pre-delivery capacity repair')
        if Recovery(r.project,r.store,r.board).expired_effects(source.id):raise EffectBlocked('settle effects')
        decision=r.store.receipt(value['diagnosis'],kind='diagnostic_decision');d=decision['payload'];scope=decision['binding']
        incident=r.store.receipt(d['incident'],kind='incident')
        diagnostic=kb.get_task(conn,scope['task']);closed=kb.latest_run(conn,scope['task'])
        if (d['action']!='hold' or not d.get('experiment') or scope['actor']!=r.project.technical_roles['cto']
                or scope['release']!=r.binding(anchor)['release'] or not diagnostic or diagnostic.status!='done'
                or not closed or closed.id!=scope['number'] or (closed.metadata or {}).get('diagnosis')!=value['diagnosis']
                or incident['binding']['task']!=source.id or incident['binding']['number']!=latest.id):
            raise ValueError('exact completed CTO hold required')
        oldrun=conn.execute('SELECT * FROM task_runs WHERE id=?',(value['source_run'],)).fetchone()
        if not oldrun or oldrun['task_id']!=source.id or not oldrun['ended_at'] or oldrun['id']>latest.id:
            raise ValueError('same-card historical execution required')
        baseline=r.store.receipt(graph['payload']['seed'],kind='release_seed')['payload']['snapshot']
        left=r.store.manifest(baseline);right=r.store.manifest(value['rejected_snapshot'])
        prefix=r.project.tests_dir+'/'
        if any(right.get(p)!=v for p,v in left.items()) or any(not p.startswith(prefix) for p in right.keys()-left.keys()):
            raise ValueError('rejected candidate must preserve all baseline and product bytes; additive tests only')
        before=json.loads((runtime.root/'installation.json').read_bytes());old,files=validation_files(r.project,r.store)
        if old!=graph['payload']['validation_bundle']:raise ValueError('original validator pin required')
        candidate=r.store.tree(value['rejected_snapshot'])/r.project.tests_dir
        try:inventory(files['browser.py'],candidate)
        except ValueError as error:
            if str(error)!='bounded nonempty acceptance inventory required':raise
        else:raise ValueError('historical inventory refusal must reproduce')
        new=seal_validation(r.store);tree=r.store.tree(new)
        if (tree/'suite.py').read_bytes()!=files['suite.py'].read_bytes():raise ValueError('suite gate must remain unchanged')
        result=inventory(tree/'browser.py',candidate)
        if not 20<len(result['criteria'])<=256 or not result['cases']:raise ValueError('additive cumulative-capacity evidence required')
        after={**before,'validation_bundle':new}
        key=r.store.record('capacity_repair',r.binding(anchor),dict(project=r.project.fingerprint(),request=value,
            before=before,after=after,prior_graph=prior,review=spec['review'],source=source.id,
            source_run=latest.id,baseline=baseline,rejected_snapshot=value['rejected_snapshot'],
            reproduced_error='bounded nonempty acceptance inventory required',criteria=len(result['criteria']),cases=len(result['cases']),
            assisted=True,delivery_approval=False,authority='Owner authorized additive capacity repair and rejected-attempt diagnosis'))
        write_json(path,{'receipt':key});write_json(runtime.root/'installation.json',after)
        return dict(receipt=key,assisted=True,delivery_approval=False)
