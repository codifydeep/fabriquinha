"""Negative native authorization tests; no task dispatch or model calls."""
import subprocess
from broker_smoke import CONTAINER

SCRIPT = '''import json,sqlite3,uuid,urllib.request,urllib.error
from pathlib import Path
con=sqlite3.connect('/broker-state/leases.sqlite')
settings=json.loads(Path('/broker-state/native.json').read_text())
agent=next(iter(settings['agents']))
task=con.execute('SELECT task_id FROM native_bindings ORDER BY rowid DESC LIMIT 1').fetchone()[0]
before=con.execute('SELECT count(*) FROM grants').fetchone()[0]
owner=Path('/broker-state/token').read_text()
for label,payload in [
 ('terminal_native_task',{'task_id':task,'agent_id':agent}),
 ('forged_task',{'task_id':str(uuid.uuid4()),'agent_id':agent}),
 ('unenrolled_agent',{'task_id':task,'agent_id':str(uuid.uuid4())}),
 ('caller_selected_mode',{'task_id':task,'agent_id':agent,'mode':'implementation'})]:
 request=urllib.request.Request('http://127.0.0.1:8090/v1/native-grants',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+owner,'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=15) as response: status=response.status
 except urllib.error.HTTPError as error:status=error.code
 assert status==400,(label,status)
 print('PASS: '+label+' rejected')
assert con.execute('SELECT count(*) FROM grants').fetchone()[0]==before
'''

if __name__ == '__main__':
    subprocess.run(['docker', 'exec', '-i', CONTAINER, 'python', '-c', SCRIPT], check=True, timeout=60)
