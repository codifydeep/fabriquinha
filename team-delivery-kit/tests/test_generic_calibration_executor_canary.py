import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import generic_calibration_executor_canary as canary
from generic_harness_calibration import run,digest
from generic_calibration_input_probe import run as probe


class ExecutorCanaryTests(unittest.TestCase):
    def test_lost_start_ack_observes_original_job_without_restarting(self):
        images,docker,command,stdout,effects=self.fake()
        lost=[False]
        def uncertain(method,path,body=None):
            result=docker(method,path,body)
            if method=='POST' and path.endswith('/start') and not lost[0]:
                lost[0]=True;raise TimeoutError('start ack lost')
            return result
        with tempfile.TemporaryDirectory() as directory,patch.object(canary,'BASE',Path(directory)),\
                patch.object(canary,'docker',side_effect=uncertain),patch.object(canary,'command',side_effect=command),\
                patch.object(canary,'stdout',side_effect=stdout):
            with self.assertRaises(TimeoutError):canary.qualify(images['engine'],images['seed'])
            root=next(Path(directory).iterdir())
            self.assertEqual(canary.qualify(images['engine'],images['seed'],root)['status'],'passed')
            self.assertEqual(len([e for e in effects if e[0]=='start']),4)
            self.assertEqual(len([e for e in effects if e[0]=='cp']),4)

    def test_uncertain_copy_stays_visible_without_replaying(self):
        images,docker,command,stdout,effects=self.fake()
        def uncertain(*args):
            command(*args)
            if args[0]=='cp':raise TimeoutError('copy acknowledgement lost')
        with tempfile.TemporaryDirectory() as directory,patch.object(canary,'BASE',Path(directory)),\
                patch.object(canary,'docker',side_effect=docker),patch.object(canary,'command',side_effect=uncertain),\
                patch.object(canary,'stdout',side_effect=stdout):
            with self.assertRaises(TimeoutError):canary.qualify(images['engine'],images['seed'])
            root=next(Path(directory).iterdir())
            with self.assertRaises(ValueError):canary.qualify(images['engine'],images['seed'],root)
            self.assertEqual(len([e for e in effects if e[0]=='cp']),1)
            self.assertFalse((root/'qualification.json').exists())

    def test_lost_create_ack_resumes_exact_container_without_replaying_creation(self):
        images,docker,command,stdout,effects=self.fake()
        lost=[False]
        def uncertain(method,path,body=None):
            result=docker(method,path,body)
            if '/create?name=delivery-kit-port2-executor-seed-' in path and not lost[0]:
                lost[0]=True;raise TimeoutError('ack lost after creation')
            return result
        with tempfile.TemporaryDirectory() as directory,patch.object(canary,'BASE',Path(directory)),\
                patch.object(canary,'docker',side_effect=uncertain),patch.object(canary,'command',side_effect=command),\
                patch.object(canary,'stdout',side_effect=stdout):
            with self.assertRaises(TimeoutError):canary.qualify(images['engine'],images['seed'])
            root=next(Path(directory).iterdir())
            result=canary.qualify(images['engine'],images['seed'],root)
            self.assertEqual(result['status'],'passed')
            self.assertEqual(len([e for e in effects if e[0]=='create']),5)
            self.assertEqual(len([e for e in effects if e[0]=='volume']),4)

    def fake(self,mutate=False):
        images={'engine':'sha256:'+'a'*64,'seed':'sha256:'+'b'*64}
        volumes={};containers={};dirs={};effects=[]
        def docker(method,path,body=None):
            if path.startswith('/images/'):
                return dict(Id=path[len('/images/'):].removesuffix('/json'),Config={'Env':['PATH=/usr/bin']})
            if path=='/volumes/create':
                volumes[body['Name']]=copy.deepcopy(body);effects.append(('volume',body['Name']));return body
            if path.startswith('/volumes/'):return copy.deepcopy(volumes.get(path.split('/')[-1]))
            if '/create?name=' in path:
                name=path.split('name=')[1]
                info=dict(Id='id-'+str(len(containers)),Image=body['Image'],Config={k:copy.deepcopy(v)
                    for k,v in body.items() if k!='HostConfig'},HostConfig=copy.deepcopy(body['HostConfig']),
                    Mounts=[dict(Type='volume',Name=m['Source'],Destination=m['Target'],RW=not m['ReadOnly'])
                        for m in body['HostConfig']['Mounts']],State={'Status':'created','Running':False,'ExitCode':0})
                containers[name]=info;effects.append(('create',name));return {'Id':info['Id']}
            key=path.split('/')[2]
            info=next((v for n,v in containers.items() if key in (n,v['Id'])),None)
            if method=='GET':return copy.deepcopy(info)
            info['State']={'Status':'exited','Running':False,'ExitCode':0};effects.append(('start',key));return {}
        def command(*args):
            effects.append(tuple(args))
            if args[0]=='cp':dirs[args[2].split(':/')[1]]=Path(args[1].removesuffix('/.'))
            if args[0]=='rm':
                info=next(v for v in containers.values() if v['Id']==args[1])
                self.assertIn(info['State']['Status'],('created','exited'))
                self.assertEqual(info['Config']['Labels']['delivery-kit.owner'],canary.OWNER)
        def stdout(cid):
            info=next(v for v in containers.values() if v['Id']==cid);cmd=info['Config']['Cmd']
            policy=json.loads((dirs['policy']/'policy.json').read_text())
            if cmd[0]=='-c':return json.dumps(dict(snapshots_readonly=True,socket_absent=True,credentials_absent=True,node_runtime=True))
            if cmd[0]=='/generic_harness_calibration.py':
                result=run(dirs['candidate'],dirs['controls'],policy,digest(policy))
                if mutate:(dirs['candidate']/'app/value.txt').write_text('tampered')
                return json.dumps(result)
            return json.dumps(probe(dirs['candidate'],dirs['previous'],dirs['controls'],policy,digest(policy),cmd[-1]))
        return images,docker,command,stdout,effects

    def test_qualification_never_grants_native_approval_and_retires_only_exact_owned_helpers(self):
        images,docker,command,stdout,effects=self.fake()
        with tempfile.TemporaryDirectory() as directory,patch.object(canary,'BASE',Path(directory)),\
                patch.object(canary,'docker',side_effect=docker),patch.object(canary,'command',side_effect=command),\
                patch.object(canary,'stdout',side_effect=stdout):
            result=canary.qualify(images['engine'],images['seed'])
            self.assertEqual(result['status'],'passed');self.assertFalse(result['native_approvals'])
            self.assertFalse(result['product_state_changed']);self.assertEqual(result['volumes_preserved'],4)
            self.assertEqual(len([e for e in effects if e[0]=='rm']),5)
            self.assertEqual(len([e for e in effects if e[0]=='start']),4)
            self.assertTrue((Path(result['archive'])/'qualification.json').exists())

    def test_changed_snapshot_fails_after_probe_and_preserves_all_resources_without_replay(self):
        images,docker,command,stdout,effects=self.fake(mutate=True)
        with tempfile.TemporaryDirectory() as directory,patch.object(canary,'BASE',Path(directory)),\
                patch.object(canary,'docker',side_effect=docker),patch.object(canary,'command',side_effect=command),\
                patch.object(canary,'stdout',side_effect=stdout):
            with self.assertRaises(ValueError):canary.qualify(images['engine'],images['seed'])
            self.assertFalse(any(e[0]=='rm' for e in effects))
            root=next(Path(directory).iterdir())
            self.assertFalse((root/'qualification.json').exists())
            self.assertTrue((root/'calibration-result.json').exists())
            self.assertEqual(len([e for e in effects if e[0]=='cp']),4)
