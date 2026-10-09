"""Offline synthetic controls for the QA detector, never product delivery code."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

HTML='''<!doctype html><meta charset="utf-8"><title>Synthetic detector control</title>
<form><label>Title<input id="title"></label><button>Submit feedback</button></form>
<input id="search" type="search" aria-label="Search feedback">
<button id="open">Open</button><button id="completed">Completed</button>
<select id="sort" aria-label="Sort feedback"><option>Newest first</option><option>Oldest first</option></select>
<p id="feedback-latest-match" role="status" aria-live="polite"></p>
<script>
const variant=__VARIANT__, indicator=document.getElementById('feedback-latest-match');
let status='',generation=0;
if(variant==='accessibility')indicator.removeAttribute('aria-live');
async function refresh(){
 const stamp=++generation;
 const needle=document.getElementById('search').value;
 if(variant!=='no-pending')indicator.textContent='Newest matching: …';
 if(variant==='form-lock')document.querySelector('form button').disabled=true;
 if(variant==='draft-loss')document.getElementById('title').value='';
 let query='?q='+encodeURIComponent(needle);
 if(status&&variant!=='ignore-status')query+='&status='+status;
 try{
  const r=await fetch('/feedback/latest'+query);if(r.status!==200)throw new Error('HTTP');
  const x=await r.json();
  if(variant!=='stale'&&stamp!==generation)return;
  let valid=x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).length===1&&
     (x.latest_id===null||(typeof x.latest_id==='number'&&Number.isInteger(x.latest_id)&&x.latest_id>0));
  if(variant==='accept-extra')valid=x&&Object.hasOwn(x,'latest_id');
  if(variant==='accept-invalid')valid=x&&Object.keys(x).length===1;
  if(!valid)throw new Error('shape');
  indicator.textContent=x.latest_id===null?'Newest matching: —':'Newest matching: #'+x.latest_id;
  if(variant==='sort-sensitive'&&document.getElementById('sort').selectedIndex===1)
     indicator.textContent='Newest matching: #999';
 }catch(e){if(stamp!==generation)return;indicator.textContent='Newest matching unavailable';}
}
document.querySelector('form').addEventListener('submit',e=>e.preventDefault());
document.getElementById('search').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();refresh();}});
document.getElementById('open').addEventListener('click',()=>{status='open';refresh();});
document.getElementById('completed').addEventListener('click',()=>{status='completed';refresh();});
document.getElementById('sort').addEventListener('change',refresh);
refresh();if(variant!=='no-poll')setInterval(refresh,1000);
</script>'''


class Handler(BaseHTTPRequestHandler):
    records=[]
    variant='correct'

    def log_message(self,*args):pass

    def reply(self,status,value,mime='application/json'):
        raw=value.encode() if isinstance(value,str) else json.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(raw)));self.end_headers()
        try:self.wfile.write(raw)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_POST(self):
        if urlsplit(self.path).path.endswith('/complete'):
            self.records[0]['completed']=True;return self.reply(200,self.records[0])
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        item={'id':len(self.records)+1,'title':data['title'],'completed':False}
        self.records.append(item);self.reply(201,item)

    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/':return self.reply(200,HTML.replace('__VARIANT__',json.dumps(self.variant)),'text/html')
        if parsed.path=='/favicon.ico':return self.reply(200,'','image/x-icon')
        if parsed.path=='/health':return self.reply(200,{'status':'ok','source_sha':'a'*40})
        if parsed.path in ('/feedback','/feedback/summary','/feedback/count'):
            return self.reply(200,{'items':[dict(item) for item in self.records]})
        if parsed.path!='/feedback/latest':return self.reply(404,{'error':'Not found'})
        query=parse_qs(parsed.query,keep_blank_values=True);statuses=query.get('status',[])
        if statuses and (len(statuses)!=1 or statuses[0] not in ('open','completed')):
            return self.reply(200 if self.variant=='bad-status' else 400,{'error':'Invalid latest filter'})
        needle=query.get('q',[''])[0].strip()
        normalize=str.lower if self.variant=='no-casefold' else str.casefold
        items=[item for item in self.records if normalize(needle) in normalize(item['title']) and
               (not statuses or item['completed']==(statuses[0]=='completed'))]
        ids=[item['id'] for item in items]
        value=(min(ids) if self.variant=='oldest-id' else max(ids)) if ids else None
        if self.variant=='zero-empty' and value is None:value=0
        if self.variant=='mutates' and self.records:self.records[0]['title']='mutated by GET'
        body={'latest_id':value}
        if self.variant=='extra-api':body['extra']=True
        return self.reply(200,body)


def main():
    import browser_feedback_latest as latest
    from playwright.sync_api import sync_playwright,expect
    variants=('correct','oldest-id','no-casefold','bad-status','zero-empty','mutates','extra-api',
              'accessibility','no-pending','form-lock','draft-loss','ignore-status','stale',
              'accept-extra','accept-invalid','sort-sensitive','no-poll')
    server=ThreadingHTTPServer(('127.0.0.1',8080),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    results=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=['--no-sandbox'])
        expect.set_options(timeout=1500)
        for variant in variants:
            Handler.records=[];Handler.variant=variant;latest.ERRORS.clear()
            first,second=browser.new_context(),browser.new_context();a,b=first.new_page(),second.new_page()
            guard=latest.ConsoleGuard();note=''
            for page in (a,b):
                page.on('pageerror',lambda error:latest.ERRORS.append(str(error)))
                page.on('console',lambda message,page=page:guard.observe(page,message))
            try:
                latest.exact(first.request.get(latest.ORIGIN+'/feedback/latest'),200,{'latest_id':None})
                items,_=latest.observe_api(first.request)
                latest.observe_ui(a,b,items,expect,guard)
                assert not latest.ERRORS,'unexpected console/page error'
                passed=True
            except Exception as error:
                passed=False;note=type(error).__name__+': '+str(error)[:1200]
            finally:first.close();second.close()
            assert passed==(variant=='correct'),'detector qualification failed: '+variant+' '+note
            results.append({'variant':variant,'result':'passed' if passed else 'rejected'})
        browser.close()
    server.shutdown()
    print(json.dumps({'status':'qualified','scope':'synthetic_detector_not_product_delivery',
        'recipe_sha256':hashlib.sha256(Path(latest.__file__).read_bytes()).hexdigest(),'controls':results}))


if __name__=='__main__':main()
