"""macOS-side fixed URL verifier; private receipt, no agent commands or inputs."""
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error

OUTPUT=Path('/Users/weber/Documents/ChatGPT/Hermes/bootstrap/runtime/host-probe/http.json')
BASE='http://127.0.0.1:18765'
def fetch(path):
    try:
        with urllib.request.urlopen(BASE+path,timeout=3) as response: return response.status,json.load(response)
    except urllib.error.HTTPError as exc: return exc.code,json.load(exc)

def probe():
    code,data=fetch('/health'); assert code==200 and data['status']=='ok'
    commit=data['commit']; count=1
    for a,b,value in [(0,0,None),(12,0,'A'),(0,12,'B'),(12,13,'A'),(11,11,None)]:
        code,data=fetch(f'/winner?a={a}&b={b}')
        assert code==200 and data==dict(winner=value,commit=commit); count+=1
    for path,status in [('/winner?a=-1&b=0',400),('/winner?a=x&b=0',400),('/winner?a=1',400),('/missing',404)]:
        assert fetch(path)[0]==status; count+=1
    return dict(passed=True,commit=commit,checks=count,url=BASE,origin='macOS-host',at=time.time())

if __name__=='__main__':
    OUTPUT.parent.mkdir(parents=True,exist_ok=True)
    while True:
        try: result=probe()
        except Exception as exc: result=dict(passed=False,error=type(exc).__name__,at=time.time(),origin='macOS-host')
        temp=OUTPUT.with_suffix('.tmp'); temp.write_text(json.dumps(result)); os.replace(temp,OUTPUT)
        time.sleep(10)
