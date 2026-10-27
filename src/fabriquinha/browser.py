"""Fixed browser QA over a declarative contract frozen with the reviewed tests."""
import json
import base64
import os
from pathlib import Path
import sys
import ast
import unittest
import contextlib
from urllib.parse import urlsplit


def acceptance_manifest(folder, *, allow_empty=False):
    """Read coverage and static inventory without importing worker code on host."""
    folder=Path(folder); paths=sorted(folder.glob('acceptance.*.json'))
    if (folder/'qa.json').exists() or list(folder.glob('qa.*.json')):
        raise ValueError('legacy QA cannot be silently omitted from the Python acceptance contract')
    if not paths:
        if allow_empty and not list(folder.glob('acceptance_*.py')):return dict(version=2,criteria={},cases=[])
        raise ValueError('frozen acceptance.*.json coverage manifest required')
    criteria={}
    for path in paths:
        if path.is_symlink() or path.stat().st_size>65536:raise ValueError('bounded acceptance manifest required')
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate acceptance key')
                result[key]=value
            return result
        value=json.loads(path.read_bytes(),object_pairs_hook=unique)
        if (not isinstance(value,dict) or set(value)!={'version','criteria'} or type(value['version']) is not int
                or value['version']!=2 or not isinstance(value['criteria'],dict) or not value['criteria']):
            raise ValueError('version 2 criterion coverage required')
        for key,proof in value['criteria'].items():
            if (not isinstance(key,str) or not key.strip() or len(key)>100
                    or not isinstance(proof,dict) or set(proof)!={'cases','gates'}
                    or not isinstance(proof['cases'],list) or not isinstance(proof['gates'],list)
                    or not proof['cases'] and not proof['gates']
                    or any(not isinstance(case,str) or len(case)>300 for case in proof['cases'])
                    or any(gate not in ('full_suite','regression') for gate in proof['gates'])
                    or len(set(proof['cases']))!=len(proof['cases']) or len(set(proof['gates']))!=len(proof['gates'])):
                raise ValueError('distinct criteria with explicit browser cases or controller gates required')
            if key in criteria:
                previous=criteria[key]
                if (set(previous['cases'])&set(proof['cases'])
                        or not (set(proof['cases'])-set(previous['cases']) or set(proof['gates'])-set(previous['gates']))):
                    raise ValueError('distinct criteria coverage extensions required; duplicate coverage is not an extension')
                proof=dict(cases=sorted(set(previous['cases'])|set(proof['cases'])),
                           gates=sorted(set(previous['gates'])|set(proof['gates'])))
            criteria[key]=proof
    cases=[]
    for path in sorted(folder.glob('acceptance_*.py')):
        if path.is_symlink() or path.stat().st_size>262144:raise ValueError('bounded acceptance test source required')
        tree=ast.parse(path.read_bytes(),filename=str(path))
        for node in tree.body:
            if not isinstance(node,ast.ClassDef):continue
            methods=[n.name for n in node.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test')]
            if not methods:continue
            if (len(node.bases)!=1 or not isinstance(node.bases[0],ast.Name) or node.bases[0].id!='AcceptanceTest'
                    or len(set(methods))!=len(methods)):
                raise ValueError('explicit AcceptanceTest classes and unique test methods required')
            cases.extend(path.stem+'.'+node.name+'.'+method for method in methods)
    if not 1<=len(cases)<=128 or len(set(cases))!=len(cases) or not 1<=len(criteria)<=20:
        raise ValueError('bounded nonempty acceptance inventory required')
    referenced={case for proof in criteria.values() for case in proof['cases']}
    if referenced!=set(cases):raise ValueError('coverage must reference every real acceptance case, with no invented cases')
    return dict(version=2,criteria=criteria,cases=sorted(cases))


class AcceptanceTest(unittest.TestCase):
    """Standard unittest/Playwright tests; target supplied by the fixed runner."""
    target=None
    _browser=None
    _browser_errors=None

    def new_context(self):
        context=self._browser.new_context(service_workers='block')
        self.addCleanup(context.close)
        origin=urlsplit(self.target)
        def route(request):
            parsed=urlsplit(request.request.url)
            if (parsed.scheme,parsed.netloc)!=(origin.scheme,origin.netloc):
                self._browser_errors.append('unexpected browser origin');request.abort()
            else:request.continue_()
        context.route('**/*',route)
        def deny_socket(socket):
            self._browser_errors.append('websocket outside the qualified HTTP stack');socket.close()
        context.route_web_socket('**/*',deny_socket)
        def page_opened(page):
            page.on('pageerror',lambda error:self._browser_errors.append(str(error)[:500]))
            page.on('console',lambda message:self._browser_errors.append(message.text[:500]) if message.type=='error' else None)
        context.on('page',page_opened)
        return context


def acceptance_evaluate(folder,source,target,*,result=None,screenshot=False):
    """Run the complete frozen Python suite against either fixed local target."""
    from playwright.sync_api import sync_playwright
    folder=Path(folder);manifest=acceptance_manifest(folder)
    result=result if result is not None else unittest.TestResult()
    start=result.testsRun;failures=len(result.failures);errors=len(result.errors)
    skips=len(result.skipped);expected=len(result.expectedFailures);unexpected=len(result.unexpectedSuccesses)
    stage='health';browser_errors=[];image=None
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                request=playwright.request.new_context()
                try:
                    for path,value in (('/health',{'status':'ok'}),('/identity',{'source_sha':source})):
                        response=request.get(target+path,max_redirects=0,timeout=10000)
                        if response.status!=200 or response.json()!=value:raise ValueError('deployed health/identity mismatch')
                finally:request.dispose()
                AcceptanceTest.target=target;AcceptanceTest._browser=browser;AcceptanceTest._browser_errors=browser_errors
                # An absolute trusted module binding, never a product import.
                sys.modules['fabriquinha_acceptance']=sys.modules[__name__]
                stage='discovery'
                loader=unittest.TestLoader();tests=loader.discover(str(folder),pattern='acceptance_*.py',top_level_dir=str(folder))
                def flatten(suite):
                    for item in suite:
                        if isinstance(item,unittest.TestSuite):yield from flatten(item)
                        else:yield item
                discovered=list(flatten(tests))
                if (loader.errors or sorted(t.id() for t in discovered)!=manifest['cases']
                        or any(not isinstance(t,AcceptanceTest) for t in discovered)):
                    raise ValueError('acceptance discovery differs from frozen static inventory')
                stage='assertion';tests.run(result)
                if (result.testsRun-start!=len(manifest['cases']) or len(result.failures)!=failures
                        or len(result.errors)!=errors or len(result.skipped)!=skips
                        or len(result.expectedFailures)!=expected or len(result.unexpectedSuccesses)!=unexpected):
                    details=[case.id()+': '+detail[-1600:] for case,detail in
                        [*result.failures[failures:],*result.errors[errors:]][:4]]
                    raise AssertionError('full acceptance suite failed, skipped or did not run completely: '+str(details))
                if browser_errors:raise AssertionError('browser runtime errors: '+str(browser_errors[:8]))
            finally:
                if screenshot and AcceptanceTest._browser is browser:
                    context=AcceptanceTest().new_context()
                    try:
                        page=context.new_page();page.goto(target,wait_until='domcontentloaded',timeout=10000)
                        image=page.screenshot(type='png',timeout=5000)
                        if len(image)>1024*1024:raise ValueError('bounded browser screenshot required')
                    except Exception:
                        image=None
                    finally:context.close()
                AcceptanceTest.target=None;AcceptanceTest._browser=None;AcceptanceTest._browser_errors=None
                browser.close()
        if browser_errors:raise ValueError('browser runtime errors: '+str(browser_errors[:8]))
        if screenshot and image is None:raise ValueError('browser screenshot unavailable')
    except Exception as error:
        report=dict(version=1,status='failed',source_sha=source,checks=[],cases=manifest['cases'],
            errors=[str(error)[:1000]],phase=stage,failure_kind='behavior' if stage=='assertion' else 'infrastructure')
        if image is not None:report['png_base64']=base64.b64encode(image).decode()
        return report
    report=dict(version=1,status='passed',source_sha=source,
        checks=[key for key,value in manifest['criteria'].items() if value['cases']],cases=manifest['cases'],errors=[])
    if screenshot:report['png_base64']=base64.b64encode(image).decode()
    return report


def expected_checks(folder,mode=1):
    if mode==2:
        return [key for key,value in acceptance_manifest(folder)['criteria'].items() if value['cases']]
    return [check['id'] for check in load_contract(folder)['checks']]


def author_protocol(mode=1):
    """Feature-neutral format documentation, never prewritten product checks."""
    if mode==2:
        return dict(version=2,format='unittest + Playwright',files=['acceptance_*.py','acceptance.*.json'],
            manifest_example={'version':2,'criteria':{'CRITERION_ID':{'cases':['acceptance_feature.Feature.test_behavior'],'gates':[]}}},
            import_statement='from fabriquinha_acceptance import AcceptanceTest',
            test_class='class Feature(AcceptanceTest): define ordinary test_* methods with assertions; use self.target and self.new_context()',
            rules=[
                'The same complete frozen acceptance suite runs against preview and deployed HTTP targets. Never start your own app in acceptance tests; self.target is supplied by the controller.',
                'Create independent self.new_context() sessions for independent users; contexts and browser close automatically. Use standard Playwright and unittest assertions, not source-string checks.',
                'Use domcontentloaded plus explicit readiness assertions. Use time.monotonic() and a bounded expectation when the brief specifies an elapsed-time limit.',
                'Declare every real acceptance case in criterion coverage. All cases are discovered and run; no case filters, load_tests overrides, skips, test inheritance or hidden discovery.',
                'A criterion may reference several cases and a case may cover several criteria. Coverage is semantic and must be independently reviewed.',
                'Only full_suite and regression are controller gates. Use gates only for corresponding delivery-quality criteria, never to replace a user-visible behavior test.',
                'At most 20 distinct criteria and 128 cases. Append a new manifest and test file per increment; preserve all baseline tests and manifests byte-for-byte.',
                'To extend an existing criterion in a later increment, repeat its ID in the new manifest with only additional case IDs. Coverage is the union of all immutable manifests; never replace earlier cases or edit their manifest. Exact duplicate coverage is rejected.',
                'Server data is shared. Use explicit repeatable fixtures through supported product behavior; new browser contexts isolate cookies/storage, not server data. Do not add privileged test-only application endpoints.',
                'Same-origin HTTP only, no WebSockets/CDNs/downloads. Register cleanup for any extra resources. No browser console/page errors.',
                'New candidate tests can be corrected by their author before independent freeze. Reviewers never edit the author. Frozen Python test revision is not qualified; escalate that technical limitation to CTO, not CEO. Business changes or removing coverage require CEO approval.'])
    if mode!=1:raise ValueError('known browser protocol required')
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


def preview(root, tests_dir, source, *, mode=1,result=None):
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
        return (acceptance_evaluate(Path(root)/tests_dir,source,target,result=result) if mode==2
                else evaluate(Path(root)/tests_dir,source,target))
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
    evaluate_fn=acceptance_evaluate if os.environ.get('FABRIQUINHA_BROWSER_CONTRACT')=='2' else evaluate
    with open(os.devnull,'w') as quiet,contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
        report=evaluate_fn(Path('/qa-contracts'),os.environ['FABRIQUINHA_SOURCE_SHA'],'http://web:8080',screenshot=True)
    print(json.dumps(report))
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
