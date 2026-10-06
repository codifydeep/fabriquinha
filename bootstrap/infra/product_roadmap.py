"""Reviewed, capability-aware DAG planning. Historical messages never release dependencies."""
import json
from product_policy import context,CAPABILITIES
from product_workspace import digest,Workspace
from product_claim import NativeClaim
from product_recovery import CONFIGS,is_test

def eligible(graph,accepted):
    return [key for key,node in graph.items() if key not in accepted and set(node['parents'])<=set(accepted)]

def validate_spec(packet,action,spec):
    if action=='dispatch_work':
        if not isinstance(spec,dict) or set(spec)!={'parent','title','brief','capability','tdd_mode'}:raise ValueError('exact executable work specification required')
        if spec['parent'] not in packet['eligible']:raise PermissionError('dependencies not accepted')
        if spec['capability'] not in packet['available_capabilities']:raise PermissionError('capability unavailable; request platform work first')
        if spec['tdd_mode'] not in ('feature','bugfix','refactor'):raise ValueError('registered evidence mode required')
        if CAPABILITIES[spec['capability']]['adapter']=='document' and spec['tdd_mode']!='refactor':raise PermissionError('documents use characterization, not fabricated Red')
        if not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=8000 or not isinstance(spec['title'],str) or not 10<=len(spec['title'])<=200:raise ValueError('bounded actionable card required')
    elif action=='accept_work_item':
        if not isinstance(spec,dict) or set(spec)!={'parent','deliveries','reason'} or spec['parent'] not in packet['eligible']:raise PermissionError('eligible work item required')
        proofs=packet['integrated_children'].get(spec['parent'],[])
        if not spec['deliveries'] or set(spec['deliveries'])!=set(proofs) or spec['parent'] in packet['busy_parents']:raise PermissionError('all integrated evidence required; no unfinished child')
        if not isinstance(spec['reason'],str) or len(spec['reason'])<100:raise ValueError('independent acceptance rationale required')
    elif action=='request_capability':
        if not isinstance(spec,dict) or set(spec)!={'parent','capability','reason'} or spec['parent'] not in packet['eligible'] or spec['capability'] not in CAPABILITIES:raise ValueError('registered capability and eligible scope required')
        if spec['capability'] in packet['available_capabilities'] or len(spec['reason'])<100:raise ValueError('explain actual missing precondition')
    else:raise PermissionError('unregistered planning action')

def tick(c):
    from hermes_cli import kanban_db as kb
    from product_autonomy import api
    if not c.cfg.get('dag_planning'):return
    roadmap=json.loads((c.board/'product-roadmap.json').read_text());nodes=roadmap['graph']['nodes']
    accepted={key for key in nodes if c.get('accepted-work:'+key)}
    ready=eligible(nodes,accepted)
    if not ready:
        c.put('planning-frontier',dict(eligible=[],busy=[],selectable=[],integrated_children={},next_action='Review release acceptance or unresolved graph dependencies; never automatic homologation'))
        return
    publications=[json.loads(r[0]) for r in c.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
    from product_delivery_lineage import integrated_index
    integrated=integrated_index(c.cfg['cards'],publications)
    from product_environment import accepted as environments
    integrated.update(environments(c))
    children={};busy=set()
    from product_platform import requests
    for _,pending in requests(c.db):
        if pending.get('state')!='READY':
            parent=pending.get('parent')
            if parent in nodes:busy.add(parent)
    for tid,card in c.cfg['cards'].items():
        parent=next((k for k,v in roadmap['nodes'].items() if v==card.get('parent_work_item')),None)
        if not parent or not (card.get('autonomous') or card.get('environment_delivery')) or c.get('superseded:'+tid):continue
        if tid in integrated:
            source=integrated[tid].get('source_task',tid)
            if source not in children.setdefault(parent,[]):children[parent].append(source)
        elif card.get('rework_pr') and any(p['pr']==card['rework_pr'] and p['state']=='INTEGRATED' for p in publications):continue
        else:busy.add(parent)
    # No duplicate planning for an already active parent. Other independent nodes
    # remain available; a blocked child has its own owner/recovery path.
    selectable=[p for p in ready if p not in busy]
    c.put('planning-frontier',dict(eligible=ready,busy=sorted(busy),selectable=selectable,integrated_children=children))
    if not selectable:return
    head=api('git/ref/heads/release/v0.1')['object']['sha']
    available=c.cfg.get('enabled_capabilities',{})
    packet=dict(head=head,eligible=selectable,available_capabilities=available,integrated_children=children,busy_parents=sorted(busy),
        integration_evidence={tid:integrated[tid] for tids in children.values() for tid in tids},
        files={n:v for n,v in c.source_files(head).items() if n!='package-lock.json'},
        nodes={k:dict(nodes[k],native_card=roadmap['nodes'][k],scope=kb.get_task(c.native,roadmap['nodes'][k]).body) for k in selectable},
        allowed_actions=['dispatch_work','accept_work_item','request_capability'],
        constraints='Plan a bounded real increment for an eligible node, or accept a fully delivered node with all evidence. Do not endlessly repeat a partial increment or infer completion from conversation. Choose specialist capability; no hardcoded backend sequence. QA independently checks completeness and feasibility. Missing capability becomes DevOps work, not a CEO architecture question.')
    key='dag-plan:'+digest(dict(head=head,accepted=sorted(accepted),children=children,eligible=selectable,capabilities=available))
    if c.get(key+':applied'):return
    tid=c.get(key)
    if not tid:tid=c.team_task(key,packet,'TECHLEAD — Plan dependency-ready specialist work',capability='planning');c.put(key,tid)
    tid=c.escalate(tid,key);answer=c.decision(tid)
    if not answer or answer[1]['decision']!='approve':return
    proposal,verdict=answer;spec=proposal['specification'];validate_spec(packet,proposal['action'],spec)
    if proposal['head']!=head:raise PermissionError('planning base changed; new plan required')
    parent=spec['parent']
    if proposal['action']=='accept_work_item':
        c.put('accepted-work:'+parent,dict(task=tid,proposal_sha256=digest(proposal),reviewer=verdict['reviewer'],deliveries=spec['deliveries'],reason=spec['reason'],base=head))
        kb.add_comment(c.native,roadmap['nodes'][parent],'techlead','Work item accepted by independent planning review '+tid+'. Integrated evidence: '+', '.join(spec['deliveries'])+'. Not release homologation.')
    elif proposal['action']=='request_capability':
        from product_platform import request_capability
        request_capability(c,spec,head,tid)
    else:
        cap=spec['capability'];registered=available[cap];policy=context(cap)
        from product_capabilities import preflight
        preflight(cap,registered)
        if registered['adapter']=='deployment':
            from product_environment import dispatch
            dispatch(c,key+':child',head,roadmap['nodes'][parent],spec['brief'],spec['title'])
            c.put(key+':applied',dict(proposal_sha256=digest(proposal),action=proposal['action']));return
        files=c.source_files(head);protected=[n for n in files if is_test(n) or n in CONFIGS]
        child=kb.create_task(c.native,title=spec['title'],body=spec['brief'],assignee=policy['author'],initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key+':child')
        if registered['adapter']=='document':
            from product_documents import editable
            protected=[n for n in files if not editable(n)]
        card=dict(policy,adapter=registered['adapter'],base=head,files=files,protected=protected,brief=spec['brief'],parent_work_item=roadmap['nodes'][parent],autonomous=True,
            validation_image=registered['image'],tdd_contract='case-inventory-v2',tdd_mode=spec['tdd_mode'])
        w=Workspace(c.private,NativeClaim(c.board,c.cfg['attempt'],{child:card}))
        if not c.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(child,)).fetchone():w.seed(c.cfg['attempt'],child,card['author'],head,files,protected,card['reviewer'])
        c.register(child,card);kb.unblock_task(c.native,child)
    c.put(key+':applied',dict(proposal_sha256=digest(proposal),action=proposal['action']))
