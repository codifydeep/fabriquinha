"""Synthetic QA-detector fixture, never product code or delivery evidence.

Runs only inside a network-none browser container. Known defects are intentional
negative controls; this fixture must never be copied into a product repository.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
from urllib.parse import parse_qs, urlparse

HTML = '''<!doctype html><html><head><meta charset="utf-8"></head><body>
<form id="feedback-form"><label>Title<input id="title"></label>
<label>Description<textarea id="description"></textarea></label>
<button type="submit">Submit feedback</button></form>
<input id="search" type="search" aria-label="Search feedback">
<div id="filters"><button aria-pressed="true">All</button>
<button aria-pressed="false">Open</button><button aria-pressed="false">Completed</button></div>
<select id="sort" aria-label="Sort feedback"><option value="newest">Newest</option>
<option value="oldest">Oldest</option></select><div id="feedback-list"></div>
<section id="feedback-detail" role="region" aria-label="Feedback details" hidden></section>
<script>
const variant=__VARIANT__; let selected='All',generation=0;
const panel=document.getElementById('feedback-detail');
const submit=document.querySelector('#feedback-form button');
function closeDetail(){if(variant!=='close-pending')generation++;panel.hidden=true;panel.replaceChildren();}
function content(text){panel.replaceChildren(); const p=document.createElement('p');p.textContent=text;
 panel.append(p);const close=document.createElement('button');close.textContent='Close details';
 close.addEventListener('click',closeDetail);panel.append(close);}
async function view(item){
 const stamp=++generation;panel.hidden=false;content(variant==='no-loading'?'':'Loading details…');
 if(variant==='form-lock')submit.disabled=true;
 if(variant==='writes')fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Forbidden write'})});
 const id=variant==='wrong-id'?1:item.id;
 if(variant==='extra-fetch')fetch('/feedback/'+id);
 try {const response=await fetch('/feedback/'+id); if(!response.ok)throw new Error('unavailable');
 const data=await response.json();if(variant!=='stale-response'&&stamp!==generation)return;
 panel.hidden=false;content(data.item.title+' '+(data.item.completed?'Completed':'Open'));
 if(variant==='unsafe-html')panel.querySelector('p').innerHTML=data.item.title;
 }catch(e){if(stamp!==generation)return;content(variant==='failure'?'Wrong error message':'Details unavailable');}
}
async function refresh(){
 const q=document.getElementById('search').value;
 const response=await fetch('/feedback?q='+encodeURIComponent(q));const data=await response.json();
 let items=data.items.filter(i=>selected==='All'||i.completed===(selected==='Completed'));
 items.sort((a,b)=>document.getElementById('sort').value==='oldest'?a.id-b.id:b.id-a.id);
 const list=document.getElementById('feedback-list');list.replaceChildren();
 for(const item of items){const row=document.createElement('article');row.className='feedback-item';
 const title=document.createElement('h3');title.className='feedback-title';title.textContent=item.title;
 const button=document.createElement('button');button.textContent='View details';button.addEventListener('click',()=>view(item));
 row.append(title,button);list.append(row);}
}
document.getElementById('feedback-form').addEventListener('submit',e=>e.preventDefault());
document.getElementById('search').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();refresh();}});
document.getElementById('sort').addEventListener('change',refresh);
document.querySelectorAll('#filters button').forEach(button=>button.addEventListener('click',()=>{
 selected=button.textContent;document.querySelectorAll('#filters button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));refresh();}));
refresh();
</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    records = []
    variant = 'correct'
    def log_message(self, *args): pass
    def reply(self, status, body, mime='application/json'):
        raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status); self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        parsed=urlparse(self.path);path=parsed.path
        if path=='/':return self.reply(200,HTML.replace('__VARIANT__',json.dumps(self.variant)),'text/html')
        if path=='/favicon.ico':return self.reply(200,'','image/x-icon')
        if path=='/health':return self.reply(200,{'status':'ok','source_sha':'a'*40})
        if path=='/feedback':
            needle=parse_qs(parsed.query).get('q',[''])[0].strip().casefold()
            return self.reply(200,{'items':[i for i in self.records if needle in i['title'].casefold()]})
        if path=='/feedback/summary':
            complete=sum(i['completed'] for i in self.records)
            return self.reply(200,{'total':len(self.records),'open':len(self.records)-complete,'completed':complete})
        token=path.removeprefix('/feedback/')
        if not re.fullmatch('[1-9][0-9]*',token):return self.reply(400,{'error':'Invalid feedback id'})
        item=next((i for i in self.records if i['id']==int(token)),None)
        return self.reply(200,{'item':item}) if item else self.reply(404,{'error':'Feedback not found'})
    def do_POST(self):
        path=urlparse(self.path).path
        if path.endswith('/complete'):
            item=next(i for i in self.records if i['id']==int(path.split('/')[2]))
            item['completed']=True;return self.reply(200,item)
        size=int(self.headers.get('Content-Length','0'));data=json.loads(self.rfile.read(size))
        item={'id':len(self.records)+1,'title':data['title'],'completed':False}
        self.records.append(item);self.reply(201,item)


def main():
    import browser_feedback_detail as detail
    from playwright.sync_api import sync_playwright, expect
    server=ThreadingHTTPServer(('127.0.0.1',8080),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    variants=('correct','no-loading','form-lock','wrong-id','writes','stale-response',
              'close-pending','unsafe-html','failure','extra-fetch')
    results=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=['--no-sandbox'])
        expect.set_options(timeout=1500)
        for variant in variants:
            Handler.records=[];Handler.variant=variant
            first,second=browser.new_context(),browser.new_context()
            a,b=first.new_page(),second.new_page();errors=[]
            guard=detail.ExpectedDetailFailure()
            error_note=''
            for page in (a,b):
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('console',lambda message,page=page:guard.console(page,message,errors))
            try:
                detail.observe_detail_api(first.request)
                detail.observe_detail_ui(a,b,first.request,expect,guard)
                assert not errors,'unexpected browser errors'
                passed=True
            except Exception as error:
                passed=False
                error_note=type(error).__name__+': '+str(error)[:1600]
            finally:
                first.close();second.close()
            assert passed==(variant=='correct'),'QA detector qualification failed: '+variant+' '+error_note
            results.append({'variant':variant,'result':'passed' if passed else 'rejected'})
        browser.close()
    server.shutdown()
    print(json.dumps({'status':'qualified','scope':'synthetic_recipe_detector_not_product_delivery',
        'recipe_sha256':hashlib.sha256(Path(detail.__file__).read_bytes()).hexdigest(),
        'controls':results}))


if __name__=='__main__':main()
