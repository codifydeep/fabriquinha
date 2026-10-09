"""Fixed newest-match acceptance; never replaces count/detail/legacy QA."""
import base64
import json
import re
import sys
from urllib.parse import urlsplit,parse_qs

ORIGIN='http://fixture:8080'
LATEST_URL=re.compile(re.escape(ORIGIN)+r'/feedback/latest(?:\?.*)?$')
ERRORS=[]


class ConsoleGuard:
    MESSAGE='Failed to load resource: net::ERR_FAILED'

    def __init__(self):self.pending=[]

    def injected(self,page,url):
        assert LATEST_URL.fullmatch(url),'exact injected latest URL'
        self.pending.append((page,url))

    def observe(self,page,message):
        if message.type!='error':return
        candidate=(page,message.location.get('url'))
        if message.text==self.MESSAGE and candidate in self.pending:
            self.pending.remove(candidate)
        else:ERRORS.append(message.text)


def exact(response,status,expected):
    assert response.status==status,'latest HTTP status'
    assert response.headers.get('content-type','').split(';')[0].strip()=='application/json','latest MIME'
    assert json.dumps(response.json(),sort_keys=True)==json.dumps(expected,sort_keys=True),'latest exact JSON shape/types'


def observe_api(request):
    items=[]
    for title in ('Latest QA Alpha','latest qa Beta','Straße newest QA'):
        response=request.post(ORIGIN+'/feedback',data={'title':title})
        assert response.status==201
        item=response.json();assert type(item['id']) is int and item['id']>0;items.append(item)
    assert request.post(ORIGIN+'/feedback/'+str(items[0]['id'])+'/complete').status==200
    before=[request.get(ORIGIN+p).json() for p in ('/feedback','/feedback/summary','/feedback/count')]
    for query,ident in [('',items[2]['id']),('?status=open',items[2]['id']),
        ('?status=completed',items[0]['id']),('?q=LATEST%20QA',items[1]['id']),
        ('?status=open&q=latest%20qa',items[1]['id']),('?q=latest%20qa&status=completed',items[0]['id']),
        ('?q=STRASSE',items[2]['id']),('?q=absent-latest-needle',None),
        ('?q=%20%20',items[2]['id']),('?q=%27%20OR%201%3D1%20--',None)]:
        exact(request.get(ORIGIN+'/feedback/latest'+query),200,{'latest_id':ident})
    for query in ('?status=','?status=all','?status=invalid','?status=open&status=completed'):
        exact(request.get(ORIGIN+'/feedback/latest'+query),400,{'error':'Invalid latest filter'})
    assert [request.get(ORIGIN+p).json() for p in ('/feedback','/feedback/summary','/feedback/count')]==before,'latest GET mutated data'
    return items,['latest_exact_json','latest_filters_unicode','latest_empty_null','latest_invalid_status','latest_read_only']


def observe_ui(a,b,items,expect,guard):
    for page in (a,b):
        page.goto(ORIGIN+'/',wait_until='networkidle')
        indicator=page.locator('#feedback-latest-match')
        expect(indicator).to_have_attribute('role','status');expect(indicator).to_have_attribute('aria-live','polite')
        expect(indicator).to_have_text('Newest matching: #'+str(items[2]['id']))
    title=a.get_by_label('Title',exact=True);title.fill('Latest preserved draft')
    query=a.get_by_role('searchbox',name='Search feedback',exact=True)
    query.fill('Latest QA');query.press('Enter');a.get_by_role('button',name='Open',exact=True).click()
    indicator=a.locator('#feedback-latest-match')
    expect(indicator).to_have_text('Newest matching: #'+str(items[1]['id']))
    expect(b.locator('#feedback-latest-match')).to_have_text('Newest matching: #'+str(items[2]['id']))
    a.get_by_role('combobox',name='Sort feedback',exact=True).select_option(label='Oldest first')
    expect(indicator).to_have_text('Newest matching: #'+str(items[1]['id']))
    held=[];replies={}
    def hold(route):
        needle=parse_qs(urlsplit(route.request.url).query).get('q',[''])[0]
        if needle.startswith('latest-probe-'):
            assert route.request.method=='GET';held.append(route)
            if needle in replies:route.fulfill(status=200,content_type='application/json',body=replies[needle])
        else:route.continue_()
    a.route(LATEST_URL,hold)
    def search(needle):
        query.fill(needle);query.press('Enter')
        for _ in range(100):
            routes=[r for r in held if parse_qs(urlsplit(r.request.url).query).get('q')==[needle]]
            if routes:return routes[0]
            a.wait_for_timeout(25)
        raise AssertionError('latest request missing')
    def answer(route,body):
        if route.request.failure=='net::ERR_ABORTED':return
        try:route.fulfill(status=200,content_type='application/json',body=body)
        except Exception:
            if route.request.failure!='net::ERR_ABORTED':raise
    stale=search('latest-probe-stale');expect(indicator).to_have_text('Newest matching: …')
    expect(a.get_by_role('button',name='Submit feedback',exact=True)).to_be_enabled()
    current=search('latest-probe-current');replies['latest-probe-current']=json.dumps({'latest_id':None})
    answer(current,replies['latest-probe-current']);expect(indicator).to_have_text('Newest matching: —')
    answer(stale,json.dumps({'latest_id':999}));a.wait_for_timeout(200)
    expect(indicator).to_have_text('Newest matching: —')
    for index,invalid in enumerate((True,0,-1,1.5,'1')):
        needle='latest-probe-invalid-'+str(index);route=search(needle)
        replies[needle]=json.dumps({'latest_id':invalid});answer(route,replies[needle])
        expect(indicator).to_have_text('Newest matching unavailable')
        expect(title).to_have_value('Latest preserved draft')
        expect(a.get_by_role('button',name='Submit feedback',exact=True)).to_be_enabled()
    for index,body in enumerate((json.dumps({'latest_id':1,'extra':True}),'[]','broken')):
        needle='latest-probe-shape-'+str(index);route=search(needle);replies[needle]=body;answer(route,body)
        expect(indicator).to_have_text('Newest matching unavailable')
    failed=search('latest-probe-network');guard.injected(a,failed.request.url);failed.abort('failed')
    expect(indicator).to_have_text('Newest matching unavailable')
    query.fill('Latest QA');query.press('Enter')
    expect(indicator).to_have_text('Newest matching: #'+str(items[1]['id']))
    created=b.request.post(ORIGIN+'/feedback',data={'title':'Latest QA fresh poll'});assert created.status==201
    ident=created.json()['id']
    expect(indicator).to_have_text('Newest matching: #'+str(ident),timeout=10000)
    expect(b.locator('#feedback-latest-match')).to_have_text('Newest matching: #'+str(ident),timeout=10000)
    expect(title).to_have_value('Latest preserved draft')
    return ['latest_accessibility','latest_composed_filters','latest_independent_contexts','latest_sort_independence',
        'latest_pending_no_form_lock','latest_stale_discarded','latest_shape_types','latest_network_failure',
        'latest_draft_preserved','latest_recovery','latest_shared_poll']


def run(scenario):
    if scenario not in ('feedback-board-latest-api-v1','feedback-board-latest-ui-v1'):raise ValueError('fixed latest scenario required')
    ERRORS.clear()
    from playwright.sync_api import sync_playwright,expect
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox']);first=browser.new_context();second=browser.new_context()
        health=first.request.get(ORIGIN+'/health').json()
        assert health.get('status')=='ok' and re.fullmatch('[a-f0-9]{40}',health.get('source_sha',''))
        exact(first.request.get(ORIGIN+'/feedback/latest'),200,{'latest_id':None})
        items,checks=observe_api(first.request)
        a=first.new_page();b=second.new_page();guard=ConsoleGuard()
        for page in (a,b):
            page.on('pageerror',lambda error:ERRORS.append(str(error)))
            page.on('console',lambda message,page=page:guard.observe(page,message))
        if scenario.endswith('ui-v1'):checks+=observe_ui(a,b,items,expect,guard)
        else:a.goto(ORIGIN+'/',wait_until='networkidle')
        assert not ERRORS,'unexpected latest page error'
        result={'status':'passed','source_sha':health['source_sha'],'contexts':2,'checks':checks,
            'browser_version':browser.version,'screenshot_base64':base64.b64encode(a.screenshot(full_page=True)).decode()}
        browser.close();return result


if __name__=='__main__':
    try:print(json.dumps(run(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'status':'failed','error':type(error).__name__+': '+str(error)}));raise SystemExit(1)
