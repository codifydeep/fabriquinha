"""Read-only real-private-store checks; no approvals, snapshots or GitHub writes."""
import copy,json,sqlite3
from pathlib import Path
from publication_merge import planning_provenance
packet=json.loads(Path('/deliveries/pr-review-packets/9cd74389b0ca2f5ed15e13a6fa49972016da5474ef7aa0e1cdbb2030425c106a.json').read_text())
card={'finding_dispositions':{k:{'owner':'techlead','action':'Tracked before implementation'} for k in ('H1','H2','H3','H4')}}
with sqlite3.connect('file:/deliveries/controller.db?mode=ro',uri=True) as db:
    planning_provenance(packet,card,db)
    for change in ('bytes','scope','base','dispositions'):
        p=copy.deepcopy(packet);c=copy.deepcopy(card)
        if change=='bytes': p['files']['docs/planning/v0.1/plan.md']+='changed'
        if change=='scope': p['files']['application.py']='code'
        if change=='base': p['base_sha']='0'*40
        if change=='dispositions': c['finding_dispositions'].pop('H3')
        try: planning_provenance(p,c,db)
        except PermissionError: pass
        else: raise AssertionError('accepted '+change)
print('PASS real private provenance; altered bytes, extra scope, wrong foundation and missing finding dispositions rejected')
packet=json.loads(Path('/deliveries/pr-review-packets/d136c79667cc522571de138ae97cf62c04a9f2ff51644dd692b5543b388c43a5.json').read_text())
with sqlite3.connect('file:/deliveries/controller.db?mode=ro',uri=True) as db:
    planning_provenance(packet,card,db)
    mutated=copy.deepcopy(packet)
    manifest=json.loads(mutated['files']['docs/planning/v0.1/approvals.json'])
    manifest['documents'][0]['review_run']=999
    mutated['files']['docs/planning/v0.1/approvals.json']=json.dumps(manifest)
    try:planning_provenance(mutated,card,db)
    except PermissionError:pass
    else:raise AssertionError('forged approval accepted')
print('PASS PR20 two-file private provenance; forged approval rejected')
