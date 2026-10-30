"""Use an isolated Compose group to prove fresh QA and idempotent observation."""
import argparse,json,sys,time,urllib.request
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.config import Project
from fabriquinha.artifacts import Store
from fabriquinha.board import Run
from fabriquinha.deployment import Deployment
from fabriquinha.effects import Pending,write_json
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--artifact',required=True)
a=p.parse_args();root=a.root.resolve()
if root.exists():raise ValueError('fresh private proof root required')
root.mkdir(mode=0o700,parents=True)
original=Project.parse(json.loads((a.source/'project.json').read_bytes()))
project=replace(original,namespace='delivery-kit-clean-qa-proof',qualification=True)
store=Store(root/'private');old=json.loads((a.source/'private/receipts'/(a.artifact+'.json')).read_bytes())
value={**old['payload'],'project':project.fingerprint()};key=store.record('artifact',old['binding'],value)
board=SimpleNamespace(ensure=lambda run:None);deployment=Deployment(project,store,board,None);artifact=deployment.read_artifact(key)
owner=Run('proof',1,'devops','integration',False,'devops','proof','contract')
review=Run('proof',2,'quality_security','integration',True,'devops','proof','contract')
end=time.monotonic()+90
while True:
 try:deployment._up(owner,artifact,'candidate');break
 except Pending:
  if time.monotonic()>end:raise
  time.sleep(.1)
before=deployment.service(artifact)
# A room demonstrates observable state contamination before the clean instance.
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
request=urllib.request.Request(before['url']+'/api/rooms',data=json.dumps({'nickname':'qa-proof'}).encode(),headers={'Content-Type':'application/json'})
with opener.open(request,timeout=5) as response:assert response.status in (200,201)
first=deployment.clean_qa(review,artifact);fresh=deployment.service(artifact)
assert fresh['container']!=before['container'] and fresh['image']==before['image']
with opener.open(fresh['url']+'/api/rooms',timeout=5) as response:
 rooms=json.load(response);assert rooms==[] or rooms.get('rooms')==[]
assert deployment.clean_qa(review,artifact)==first
assert deployment.service(artifact)['container']==fresh['container']
next_review=replace(review,number=3)
deployment.clean_qa(next_review,artifact);again=deployment.service(artifact)
assert again['container']!=fresh['container'] and again['image']==fresh['image']
result=dict(passed=True,model_calls=0,delivery_approval=False,fresh_per_execution=True,idempotent_same_execution=True,image_unchanged=True)
write_json(root/'result.json',result);print(json.dumps(result))
