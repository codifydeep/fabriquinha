"""Fixed browser QA over a declarative contract frozen with the reviewed tests."""
import json
import base64
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def author_protocol():
    """Feature-neutral format documentation, never prewritten product checks."""
    text=dict(type='string',minLength=1,maxLength=1000,pattern=r'.*\S.*')
    def action(name,fields):
        return dict(type='object',additionalProperties=False,required=['action',*fields],
            properties=dict(action={'const':name},**fields))
    check=dict(type='object',additionalProperties=False,required=['id','path','actions','selector','text'],
        properties=dict(id=text,path={**text,'pattern':r'^/(?!/)[^\\]*$'},selector=text,text=text,
            actions=dict(type='array',minItems=1,maxItems=20,items=dict(oneOf=[
                action('fill',dict(selector=text,value=dict(type='string',maxLength=8000))),
                action('click',dict(selector=text))]))))
    return dict(schema=dict(type='object',additionalProperties=False,required=['version','checks'],
        properties=dict(version={'const':1},checks=dict(type='array',minItems=1,maxItems=20,items=check))),
        rules=['Each check ID is an approved acceptance criterion. Reuse existing IDs without adding duplicate scenarios.',
            'Append missing scenarios in new qa.<package>.<release>.json files; never rewrite existing QA files.',
            'At most 20 unique scenarios across all files. Each check navigates its local path, runs actions in order, then checks locator text.',
            'Only same-origin HTTP assets/requests; no external CDNs, fonts, downloads or WebSockets.',
            'No browser page/console errors. Serve a favicon or use an embedded data icon.'])


def contract(value):
    def text(item,limit=1000):
        return isinstance(item,str) and 0<len(item.strip())<=limit
    if (not isinstance(value,dict) or set(value)!={'version','checks'} or type(value['version']) is not int
            or value['version']!=1 or not isinstance(value['checks'],list) or not 1<=len(value['checks'])<=20):
        raise ValueError('bounded versioned browser checks required')
    seen=set()
    for check in value['checks']:
        if (not isinstance(check,dict) or set(check)!={'id','path','actions','selector','text'}
                or not all(text(check[k]) for k in ('id','path','selector','text'))
                or check['id'] in seen or not check['path'].startswith('/') or check['path'].startswith('//')
                or urlsplit(check['path']).scheme or '\\' in check['path']
                or not isinstance(check['actions'],list) or not 1<=len(check['actions'])<=20):
            raise ValueError('local browser scenario with unique ID required')
        seen.add(check['id'])
        for action in check['actions']:
            if (not isinstance(action,dict) or action.get('action') not in ('fill','click')
                    or set(action)!=({'action','selector','value'} if action['action']=='fill' else {'action','selector'})
                    or not text(action['selector']) or action['action']=='fill' and
                    (not isinstance(action['value'],str) or len(action['value'])>8000)):
                raise ValueError('only bounded declarative fill/click actions allowed')
    return value['checks']


def load_contract(folder):
    """Append-only frozen files, not permission to weaken a previous scenario."""
    folder=Path(folder);checks=[]
    paths=([folder/'qa.json'] if (folder/'qa.json').exists() else [])+sorted(folder.glob('qa.*.json'))
    for path in paths:checks.extend(contract(json.loads(path.read_bytes())))
    value=dict(version=1,checks=checks);contract(value)
    return value


def main():
    from playwright.sync_api import sync_playwright, expect
    checks=contract(load_contract(Path('/qa-contracts')))
    source=os.environ['FABRIQUINHA_SOURCE_SHA']
    target='http://web:8080'
    errors=[]; completed=[]; page=None; image=None
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1280,'height':720},service_workers='block')
            def route(request):
                parsed=urlsplit(request.request.url)
                if (parsed.scheme,parsed.netloc)!=('http','web:8080'):
                    errors.append('unexpected browser origin')
                    request.abort()
                else:request.continue_()
            context.route('**/*',route)
            def deny_socket(socket):
                errors.append('websocket outside the qualified HTTP stack')
                socket.close()
            context.route_web_socket('**/*',deny_socket)
            for path,expected in (('/health',{'status':'ok'}),('/identity',{'source_sha':source})):
                response=context.request.get(target+path,max_redirects=0,timeout=10000)
                assert response.status==200 and response.json()==expected, 'deployed health/identity mismatch'
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)[:500]))
            page.on('console',lambda message:errors.append(message.text[:500]) if message.type=='error' else None)
            try:
                for check in checks:
                    page.goto(target+check['path'],wait_until='networkidle',timeout=15000)
                    for action in check['actions']:
                        locator=page.locator(action['selector'])
                        if action['action']=='fill':locator.fill(action['value'],timeout=5000)
                        else:locator.click(timeout=5000)
                    expect(page.locator(check['selector'])).to_have_text(check['text'],timeout=5000)
                    completed.append(check['id'])
                assert not errors, 'browser runtime errors'
            finally:
                if page:
                    image=page.screenshot(type='png',full_page=False,timeout=5000)
                    assert len(image)<=1024*1024, 'bounded browser screenshot required'
                browser.close()
    except Exception as error:
        print(json.dumps(dict(version=1,status='failed',source_sha=source,checks=completed,
                              errors=[*errors,str(error)[:1000]])))
        return 1
    print(json.dumps(dict(version=1,status='passed',source_sha=source,checks=completed,errors=[],
                          png_base64=base64.b64encode(image).decode())))
    return 0


if __name__=='__main__':sys.exit(main())
