"""Controller-only real Docker fault injection; no model, reviewer approval or arbitrary job."""
import json
import publish_u3_coverage as publication

SCRIPT = '''import broker as b,json,u3_delivery_review as r,durable_review_job as j
c,s=r.saved(b)
parent,_,_=r.current(b,c)
source=parent['intake']
image=b.docker('GET','/containers/'+b.PREFIX+'-execution-broker-1/json')['Image']
key=j.digest(dict(schema='u3-start-response-canary-v2',head=c['head_sha'],manifest=c['manifest_sha256'],image=image))
if j.saved(b,key):raise ValueError('real canary already exists; inspect its durable evidence, do not repeat')
counts=dict(creates=0,starts=0,injected=False)
context=b.handoff_context()
original=context.docker
name=b.PREFIX+'-controls-job-'+j.digest(dict(key=key))[:12]
def docker(method,path,data=None):
 if method=='POST' and path.startswith('/containers/create'):
  if data['Labels'].get('delivery-kit.validation-key')!=key:raise ValueError('unscoped canary create')
  counts['creates']+=1
 if method=='POST' and path=='/containers/'+name+'/start':
  counts['starts']+=1
  original(method,path,data)
  counts['injected']=True
  raise b.DockerOperationTimeout(method,path)
 return original(method,path,data)
context.docker=docker
receipt=j.run(context,key,source['base'],source['seed'],source['proof'])
if counts!={'creates':1,'starts':1,'injected':True}:raise ValueError('exact real fault injection required')
certificate=dict(schema='u3-durable-review-canary-v1',head_sha=c['head_sha'],manifest_sha256=c['manifest_sha256'],
 model_calls=0,creates=counts['creates'],starts=counts['starts'],job_receipt=receipt,delivery_approval=False)
path=b.STATE/'u3-review-durable-canary.json'
if path.exists() and json.loads(path.read_text())!=certificate:raise ValueError('canary evidence immutable')
path.write_text(json.dumps(certificate,sort_keys=True))
print(json.dumps(certificate))
'''


def main():
    print(publication.run('docker','exec','-e','PYTHONPATH=/',publication.PROJECT+'-execution-broker-1',
                          'python','-c',SCRIPT).decode().strip())


if __name__ == '__main__':main()
