"""Operator migration of the one stateless rehearsal service; no global cleanup."""
import json
import os
import subprocess
from review_controller import Controller
from e2e_controller import ATTEMPT,PROJECT,CONTAINER

c=Controller(os.environ['REVIEW_BOARD'],'/deliveries',ATTEMPT,'hermes_review_deliveries',os.environ['REVIEW_IMAGE'])
published=c.e2e.published(); assert published['merged']
info=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]
network=json.loads(subprocess.check_output(['docker','network','inspect',PROJECT+'_default']))[0]
assert info['Config']['Labels']['hermes.attempt']==ATTEMPT
assert network['Labels']['hermes.attempt']==ATTEMPT
assert set(network['Containers']) <= {info['Id']}
image=c.e2e.get('image:'+published['merge_sha']); assert image['id']==info['Image']
subprocess.run(['docker','network','disconnect',PROJECT+'_default',CONTAINER],check=True)
subprocess.run(['docker','network','rm',PROJECT+'_default'],check=True)
command=['docker','network','create','--driver','bridge']
for key,value in network['Labels'].items(): command+=['--label',key+'='+value]
subprocess.run(command+[PROJECT+'_default'],check=True)
subprocess.run(['docker','network','connect',PROJECT+'_default',CONTAINER],check=True)
after=json.loads(subprocess.check_output(['docker','inspect',CONTAINER]))[0]
assert after['Id']==info['Id'] and after['Mounts']==info['Mounts'] and after['Image']==image['id']
print('Only scoped network replaced; container, volumes, image and commit preserved; host verification still required')
