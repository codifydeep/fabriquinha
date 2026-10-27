"""Exercise the deployed-QA image as UID 10000, without host/model/network.

A fixed HTTP fixture and the actual browser driver run inside one disposable
container. This is a toolchain proof, not deployment or release acceptance.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'team-delivery-kit'))
from docker_grouping import args as grouped
from fabriquinha.effects import write_json

PROBE='''
import importlib.metadata,importlib.util,json,os,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from playwright.sync_api import sync_playwright
source='f'*40
page=b"""<!doctype html><link rel="icon" href="data:,"><button id="increment" onclick="document.querySelector('#value').textContent='1'">Increment</button><output id="value">0</output>"""
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  value={'status':'ok'} if self.path=='/health' else {'source_sha':source} if self.path=='/identity' else None
  data=json.dumps(value).encode() if value else page
  self.send_response(200);self.send_header('Content-Type','application/json' if value else 'text/html')
  self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 spec=importlib.util.spec_from_file_location('trusted_browser','/qa.py')
 driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
 report=driver.evaluate('/qa-contracts',source,'http://127.0.0.1:'+str(server.server_port))
 assert report['status']=='passed' and report['checks']==['COUNTER'],report
 assert os.getuid()==10000
 with sync_playwright() as playwright:
  browser=playwright.chromium.launch(headless=True);version=browser.version;browser.close()
 print(json.dumps(dict(uid=os.getuid(),playwright=importlib.metadata.version('playwright'),chromium=version,qa=report)))
finally:
 server.shutdown();server.server_close();thread.join(timeout=5)
'''


def qualify(root,image):
    root=Path(root).resolve()
    if root.exists() or not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('fresh private root and exact image ID required')
    if root.is_relative_to(ROOT) and subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(root)],capture_output=True).returncode:
        raise ValueError('qualification inside checkout must use a Git-ignored private root')
    inspect=json.loads(subprocess.check_output(['docker','image','inspect',image],timeout=15))[0]
    config=inspect['Config']
    if (inspect['Id']!=image or config.get('Volumes') or config.get('User')!='10000:10000' or config.get('Entrypoint')!=['python']
            or any(value.split('=',1)[0] in {'GH_TOKEN','GITHUB_TOKEN','OPENROUTER_API_KEY','TELEGRAM_BOT_TOKEN'}
                   for value in config.get('Env',[]))):
        raise ValueError('exact unprivileged deployed-QA toolchain required')
    root.mkdir(mode=0o700,parents=True);contracts=root/'contracts';contracts.mkdir(mode=0o700)
    # The container has no host credentials; only these fixed inputs are readable.
    contracts.chmod(0o755)
    write_json(contracts/'qa.json',dict(version=1,checks=[dict(id='COUNTER',path='/',
        actions=[dict(action='click',selector='#increment')],selector='#value',text='1')]))
    (contracts/'qa.json').chmod(0o444)
    name='delivery-kit-public-browser-probe-'+hashlib.sha256(str(root).encode()).hexdigest()[:16]
    driver=ROOT/'src/fabriquinha/browser.py'
    command=['docker','run','--rm','--name',name,*grouped('qa-image-probe','delivery-kit-public-browser'),
        '--network','none','--read-only','--user','10000:10000','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--memory','512m','--cpus','1','--pids-limit','256',
        '--tmpfs','/tmp:rw,nosuid,size=256m','--mount',f'type=bind,src={driver},dst=/qa.py,readonly',
        '--mount',f'type=bind,src={contracts},dst=/qa-contracts,readonly',image,'-B','-c',PROBE]
    write_json(root/'intent.json',dict(container=name,image=image,driver=hashlib.sha256(driver.read_bytes()).hexdigest()))
    reply=subprocess.run(command,capture_output=True,text=True,timeout=60)
    write_json(root/'output.json',dict(code=reply.returncode,stdout=reply.stdout,stderr=reply.stderr))
    if reply.returncode:raise RuntimeError('browser image probe failed; inspect private diagnostics; do not blindly retry Docker effects')
    report=json.loads(reply.stdout)
    if report['playwright']!='1.64.1':raise ValueError('unexpected browser package version')
    remaining=subprocess.check_output(['docker','ps','-aq','--filter','name=^/'+name+'$'],timeout=15).strip()
    if remaining:raise RuntimeError('disposable container retirement uncertain; preserve its identity')
    result=dict(image=image,architecture=inspect['Architecture'],unprivileged=True,driver=hashlib.sha256(driver.read_bytes()).hexdigest(),
        real_chromium=True,report=report,network='none',readonly_root=True,no_host_credentials_or_socket=True,
        model_calls=0,github_mutations=0,docker_jobs=1,container_retired=True,delivery_approval=False)
    write_json(root/'receipt.json',result);print(json.dumps(result,indent=2));return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args();qualify(args.root,args.image)
