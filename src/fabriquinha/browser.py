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
        properties=dict(id=text,path={**text,'pattern':r'^/(?!/)[^\\]*$'},selector=text,
            text={**text,'description':'Expected exact full locator text after whitespace normalization, not a substring or contains match.'},
            actions=dict(type='array',minItems=1,maxItems=20,items=dict(oneOf=[
                action('fill',dict(selector=text,value=dict(type='string',maxLength=8000))),
                action('click',dict(selector=text))]))))
    return dict(schema=dict(type='object',additionalProperties=False,required=['version','checks'],
        properties=dict(version={'const':1},checks=dict(type='array',minItems=1,maxItems=20,items=check))),
        rules=['Each check ID is an approved acceptance criterion. Reuse existing IDs without adding duplicate scenarios.',
            'Preserve every QA file in the protected baseline. The tests author may revise QA files introduced by the current card until independent freeze, then submit a new revision. Reviewers and diagnosticians never edit author files.',
            'One deployed check per criterion ID: do not request duplicate IDs. Assess acceptance coverage across the complete browser unittest suite, retained QA and new QA together; this declarative check is not the sole proof of every intermediate state.',
            'At most 20 unique scenarios across all files. Each check navigates its local path, runs actions in order, then compares the exact full locator text (normalized whitespace), not a substring.',
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


def evaluate(folder, source, target, *, screenshot=False):
    """One exact interpreter for immutable preview and deployed acceptance."""
    from playwright.sync_api import sync_playwright, expect
    checks=contract(load_contract(folder))
    origin=urlsplit(target)
    errors=[]; completed=[]; page=None; image=None;stage='launch'
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            context=browser.new_context(viewport={'width':1280,'height':720},service_workers='block')
            def route(request):
                parsed=urlsplit(request.request.url)
                if (parsed.scheme,parsed.netloc)!=(origin.scheme,origin.netloc):
                    errors.append('unexpected browser origin')
                    request.abort()
                else:request.continue_()
            context.route('**/*',route)
            def deny_socket(socket):
                errors.append('websocket outside the qualified HTTP stack')
                socket.close()
            context.route_web_socket('**/*',deny_socket)
            stage='health'
            for path,expected in (('/health',{'status':'ok'}),('/identity',{'source_sha':source})):
                response=context.request.get(target+path,max_redirects=0,timeout=10000)
                assert response.status==200 and response.json()==expected, 'deployed health/identity mismatch'
            page=context.new_page()
            page.on('pageerror',lambda error:errors.append(str(error)[:500]))
            page.on('console',lambda message:errors.append(message.text[:500]) if message.type=='error' else None)
            try:
                for check in checks:
                    stage='navigation'
                    page.goto(target+check['path'],wait_until='networkidle',timeout=15000)
                    stage='actions'
                    for action in check['actions']:
                        locator=page.locator(action['selector'])
                        if action['action']=='fill':locator.fill(action['value'],timeout=5000)
                        else:locator.click(timeout=5000)
                    stage='assertion'
                    expect(page.locator(check['selector'])).to_have_text(check['text'],timeout=5000)
                    completed.append(check['id'])
                stage='runtime'
                assert not errors, 'browser runtime errors'
            finally:
                if page and screenshot:
                    image=page.screenshot(type='png',full_page=False,timeout=5000)
                    assert len(image)<=1024*1024, 'bounded browser screenshot required'
                browser.close()
    except Exception as error:
        return dict(version=1,status='failed',source_sha=source,checks=completed,
                              errors=[*errors,str(error)[:1000]],phase=stage,
                              failure_kind='behavior' if stage in ('actions','assertion','runtime') else 'infrastructure')
    result=dict(version=1,status='passed',source_sha=source,checks=completed,errors=[])
    if screenshot:result['png_base64']=base64.b64encode(image).decode()
    return result


def preview(root, tests_dir, source):
    """Fixed local entrypoint, no worker-selected command or host network."""
    import subprocess
    import time
    from urllib.request import urlopen
    target='http://127.0.0.1:8080'
    process=None
    try:
        process=subprocess.Popen([sys.executable,'-B',str(Path(root)/'app.py'),'8080'],cwd=root,
            env={**os.environ,'FABRIQUINHA_SOURCE_SHA':source},
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        deadline=time.monotonic()+8
        while True:
            if process.poll() is not None:raise RuntimeError('preview application exited before readiness')
            try:
                with urlopen(target+'/health',timeout=0.5) as response:
                    if response.status==200:break
            except OSError:pass
            if time.monotonic()>=deadline:raise RuntimeError('preview application readiness timeout')
            time.sleep(0.05)
        return evaluate(Path(root)/tests_dir,source,target)
    except Exception as error:
        return dict(version=1,status='failed',source_sha=source,checks=[],errors=[str(error)[:1000]],
                    phase='launch',failure_kind='infrastructure')
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=2)


def main():
    report=evaluate(Path('/qa-contracts'),os.environ['FABRIQUINHA_SOURCE_SHA'],'http://web:8080',screenshot=True)
    print(json.dumps(report))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
