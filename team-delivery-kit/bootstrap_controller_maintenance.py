"""One operator bootstrap of a maintenance barrier absent from an old broker.

Requires a quiescent native inventory, exact controller image and owned resources.
Stops that controller before initializing the new barrier in an isolated admin
helper. Does not start a controller, replay a grant, dispatch an agent or install
an image. Unknown stop outcomes are observed once, never retried automatically.
"""
import argparse
import json
import re
import subprocess
import uuid
from docker_grouping import args as group_args

INSPECT = '{"id":{{json .Id}},"image":{{json .Image}},"running":{{json .State.Running}},"status":{{json .State.Status}},"labels":{{json .Config.Labels}},"mounts":{{json .Mounts}}}'
PROBE = '''import sys;sys.path.insert(0,"/")
import broker as b,json,urllib.request,os,sqlite3
settings=json.loads((b.STATE/"native.json").read_text());active=[]
for actor in settings["agents"]:
 req=urllib.request.Request("http://backend:8080/api/agents/"+actor+"/tasks",headers={"Authorization":"Bearer "+settings["token"],"X-Workspace-ID":settings["workspace_id"]})
 with urllib.request.urlopen(req,timeout=5) as response: tasks=json.load(response)
 if not isinstance(tasks,list):raise ValueError("incomplete native inventory")
 for task in tasks:
  if task.get("agent_id")!=actor or not task.get("workspace_id") or not task.get("runtime_id") or not task.get("status"):raise ValueError("incomplete task metadata")
  if task["workspace_id"]==settings["workspace_id"] and task["runtime_id"]==settings["runtime_id"] and task["status"] not in ("completed","failed","cancelled","canceled"):active.append(task["id"])
with b.LOCK,b.db() as con:
 leases=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
 if active or leases:raise ValueError("bootstrap requires drained old controller")
 path=b.STATE/("maintenance-bootstrap-"+sys.argv[1]+".sqlite")
 fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
 target=sqlite3.connect(path);con.backup(target);integrity=target.execute("PRAGMA integrity_check").fetchone()[0];target.close()
 if integrity!="ok":raise ValueError("backup integrity failed")
print(json.dumps(dict(native_active=0,active_leases=0,backup_integrity=integrity)))
'''
SEAL = '''import sys;sys.path.insert(0,"/")
import broker as b,controller_maintenance as m,json
m.begin(b,sys.argv[1]);value=m.seal(b,sys.argv[1])
if value.get("stage")!="sealed" or value.get("drained") is not True:raise ValueError("bootstrap not sealed; preserve state")
print(json.dumps(value,sort_keys=True))
'''


def identity(namespace, operation, current_image, candidate_image):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', namespace): raise ValueError('exact owned namespace required')
    if str(uuid.UUID(operation)) != operation: raise ValueError('canonical operation required')
    if any(not re.fullmatch(r'sha256:[a-f0-9]{64}', v) for v in (current_image, candidate_image)):
        raise ValueError('immutable images required')


def validate_controller(info, namespace, image):
    if (info['image'] != image or info['labels'].get('com.docker.compose.project') != namespace
            or info['labels'].get('com.docker.compose.service') != 'execution-broker'):
        raise ValueError('exact owned old controller required')
    mounts = [v for v in info['mounts'] if v['Destination'] == '/broker-state']
    if len(mounts) != 1 or mounts[0]['Type'] != 'volume' or mounts[0].get('Name') != namespace+'_broker_state':
        raise ValueError('exact owned broker state volume required')
    return mounts[0]['Name']


def helper(namespace, operation, image, volume, worker):
    identity(namespace, operation, image, image)
    if volume != namespace+'_broker_state' or not re.fullmatch(r'sha256:[a-f0-9]{64}', worker):
        raise ValueError('exact helper bindings required')
    return ['docker','run','--rm','--name',namespace+'-maintenance-bootstrap-'+operation,
        *group_args('maintenance-bootstrap',namespace=namespace), '--label','delivery-kit.purpose=operator-maintenance',
        '--network',namespace+'_api','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','256m','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777',
        '--mount','type=volume,source='+volume+',target=/broker-state',
        '--env','BROKER_NAMESPACE='+namespace,'--env','BROKER_WORKER_IMAGE='+worker,
        '--entrypoint','python',image,'-c',SEAL,operation]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('namespace','operation','current-image','candidate-image','worker-image'):parser.add_argument('--'+key,required=True)
    a=parser.parse_args();identity(a.namespace,a.operation,a.current_image,a.candidate_image)
    name=a.namespace+'-execution-broker-1'
    def inspect(key):return json.loads(subprocess.check_output(['docker','inspect','--format',INSPECT,key],text=True))
    info=inspect(name);volume=validate_controller(info,a.namespace,a.current_image)
    if not info['running']:raise ValueError('old controller already stopped; observe previous bootstrap instead of replaying')
    for resource,kind in ((volume,'volume'),(a.namespace+'_api','network')):
        labels=json.loads(subprocess.check_output(['docker',kind,'inspect','--format','{{json .Labels}}',resource],text=True))
        if labels.get('com.docker.compose.project')!=a.namespace:raise ValueError('owned bootstrap resource required')
    receipt=json.loads(subprocess.check_output(['docker','exec','-w','/',info['id'],'python','-c',PROBE,a.operation],text=True))
    again=inspect(name);validate_controller(again,a.namespace,a.current_image)
    if again['id']!=info['id']:raise ValueError('controller identity changed')
    try:subprocess.run(['docker','stop','--time','10',info['id']],check=True,timeout=30,stdout=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:pass  # Observe the exact handle; never reissue stop.
    stopped=inspect(info['id'])
    if stopped['running'] or stopped['status']!='exited':raise ValueError('stop outcome not confirmed; no helper or install')
    state=json.loads(subprocess.check_output(helper(a.namespace,a.operation,a.candidate_image,volume,a.worker_image),text=True))
    print(json.dumps(dict(operation_id=a.operation,backup=receipt,maintenance=state,controller_stopped=True,installed=False)))


if __name__=='__main__':main()
