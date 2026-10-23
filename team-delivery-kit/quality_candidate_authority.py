"""Host-only fixed local RPC to one pinned installed controller incarnation.

This never creates workers/jobs or runs an agent command. Unknown replies are
not worker termination: callers re-read the exact durable binding. Only the
idempotent conditional database record may mutate state; no workspace mutation,
Git write, Docker lifecycle effect, model dispatch or approval is exposed here.
"""
import json
import re
import subprocess
from quality_git_candidate import Pending,require,canonical

PROGRAM='''import sys;sys.path.insert(0,"/")
import json,broker as b,quality_candidate_rpc as rpc
print(json.dumps(rpc.invoke_json(b,sys.stdin.read(262145)),sort_keys=True))
'''


class Effects:
    def inspect(self,name):
        result=subprocess.run(['docker','container','inspect',name],capture_output=True,text=True,timeout=15,check=True)
        rows=json.loads(result.stdout);require(len(rows)==1);return rows[0]
    def execute(self,identity,value):
        raw=json.dumps(value,sort_keys=True);require(len(raw.encode())<=262144)
        result=subprocess.run(['docker','exec','-i','-w','/',identity,'python','-c',PROGRAM],input=raw,
            capture_output=True,text=True,timeout=45)
        require(result.returncode==0 and 0<len(result.stdout.encode())<=262144)
        return json.loads(result.stdout)


class Authority:
    def __init__(self,namespace,image,*,effects=None):
        require(isinstance(namespace,str) and re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace)
            and re.fullmatch('sha256:[a-f0-9]{64}',str(image)))
        self.namespace=namespace;self.image=image;self.fx=effects or Effects()
        self.name=namespace+'-execution-broker-1';self.identity=None

    def inspect_controller(self):
        info=self.fx.inspect(self.name);labels=info.get('Config',{}).get('Labels',{})
        require(re.fullmatch('[a-f0-9]{64}',str(info.get('Id'))) and info.get('Name')=='/'+self.name
            and info.get('Image')==self.image and info.get('State',{}).get('Running') is True
            and labels.get('com.docker.compose.project')==self.namespace
            and labels.get('com.docker.compose.service')=='execution-broker')
        if self.identity is not None:require(info['Id']==self.identity)
        self.identity=info['Id'];return self.identity

    def call(self,action,**kwargs):
        require(action in ('about','inspect','record'))
        if action!='about':canonical(kwargs.get('request_id'))
        value=dict(operation=action,namespace=self.namespace,**kwargs)
        try:
            identity=self.inspect_controller();result=self.fx.execute(identity,value)
            require(self.inspect_controller()==identity and isinstance(result,dict)
                and result.get('operation')=='quality_candidate_local_rpc_v2' and result.get('namespace')==self.namespace
                and result.get('delivery_approval') is False and result.get('stage') in ('available','maintenance','pending','bound'))
            if result['stage']=='maintenance':raise Pending('controller maintenance preserves candidate; no local effects')
            return result
        except (TimeoutError,subprocess.TimeoutExpired,subprocess.CalledProcessError) as error:
            raise Pending('controller reply unavailable; inspect durable binding, never replace a worker') from error

    def about(self):return self.call('about')
    def inspect(self,request):return self.call('inspect',request_id=request)
    def record(self,request,packet,repository,candidate):
        result=self.call('record',request_id=request,packet=packet,repository=repository,candidate=candidate)
        require(result['stage']=='bound');return result
