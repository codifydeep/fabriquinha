"""Fixed count API/UI acceptance; composed after legacy and detail regressions."""
import base64
import json
import re
import sys
from urllib.parse import urlsplit, parse_qs

ORIGIN = 'http://fixture:8080'
COUNT_URL = re.compile(re.escape(ORIGIN) + r'/feedback/count(?:\?.*)?$')
LAST_ERRORS = []


def exact_json(response, status, expected):
    assert response.status == status, 'count HTTP status'
    assert response.headers.get('content-type', '').split(';', 1)[0].strip() == 'application/json', 'count JSON MIME'
    assert json.dumps(response.json(), sort_keys=True) == json.dumps(expected, sort_keys=True), 'count JSON shape/types'


def observe_api(request):
    items = []
    for title in ('Match QA Alpha', 'match qa Beta', 'Straße count QA'):
        created = request.post(ORIGIN + '/feedback', data={'title': title})
        assert created.status == 201, 'count fixture create'
        item = created.json()
        assert type(item['id']) is int and item['id'] > 0, 'count fixture id'
        items.append(item)
    assert request.post(ORIGIN+'/feedback/'+str(items[0]['id'])+'/complete').status == 200
    before = [request.get(ORIGIN+p).json() for p in ('/feedback','/feedback/summary')]
    for query, count in [('',3),('?status=open',2),('?status=completed',1),
                         ('?q=match%20qa',2),('?status=open&q=MATCH%20QA',1),
                         ('?q=match%20qa&status=completed',1),('?q=STRASSE',1),
                         ('?q=absent-count-needle',0),('?q=%20%20',3),
                         ('?q=%27%20OR%201%3D1%20--',0)]:
        exact_json(request.get(ORIGIN+'/feedback/count'+query),200,{'count':count})
    for query in ('?status=','?status=all','?status=invalid','?status=open&status=completed'):
        exact_json(request.get(ORIGIN+'/feedback/count'+query),400,{'error':'Invalid count filter'})
    assert [request.get(ORIGIN+p).json() for p in ('/feedback','/feedback/summary')] == before, 'count GET mutated data'
    return ['count_exact_json','count_combined_filters','count_unicode_search',
            'count_blank_compatible','count_invalid_status','count_query_not_sql','count_read_only']


class ConsoleGuard:
    MESSAGE = 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'

    def __init__(self): self.pending = []

    def injected(self, page, url):
        assert COUNT_URL.fullmatch(url), 'exact injected count URL'
        self.pending.append((page,url))

    def observe(self, page, message):
        if message.type != 'error': return
        candidate = (page,message.location.get('url'))
        if message.text == self.MESSAGE and candidate in self.pending:
            self.pending.remove(candidate)
        else:
            LAST_ERRORS.append(message.text)


def observe_ui(a, b, expect, guard):
    for page in (a,b):
        page.goto(ORIGIN+'/',wait_until='networkidle')
        indicator = page.locator('#feedback-match-count')
        expect(indicator).to_have_attribute('role','status')
        expect(indicator).to_have_attribute('aria-live','polite')
        expect(indicator).to_have_text('Matching: 3')
    a.get_by_label('Title',exact=True).fill('Count preserved draft')
    query = a.get_by_role('searchbox',name='Search feedback',exact=True)
    query.fill('Match QA'); query.press('Enter')
    a.get_by_role('button',name='Open',exact=True).click()
    indicator = a.locator('#feedback-match-count')
    expect(indicator).to_have_text('Matching: 1')
    expect(b.locator('#feedback-match-count')).to_have_text('Matching: 3')
    a.get_by_role('combobox',name='Sort feedback',exact=True).select_option(label='Oldest first')
    expect(indicator).to_have_text('Matching: 1')
    held, replies = [], {}
    def hold(route):
        q = parse_qs(urlsplit(route.request.url).query).get('q',[''])[0]
        if q in ('count-stale-probe','count-current-probe','count-error-probe') or re.fullmatch(r'count-invalid-probe-[0-4]',q):
            assert route.request.method == 'GET', 'count must remain read-only'
            held.append(route)
            if q in replies:
                if replies[q][0] == 503: guard.injected(a,route.request.url)
                route.fulfill(status=replies[q][0],content_type='application/json',body=replies[q][1])
        else: route.continue_()
    a.route(COUNT_URL,hold)
    def search(needle):
        query.fill(needle); query.press('Enter')
        for _ in range(100):
            matches = [r for r in held if parse_qs(urlsplit(r.request.url).query).get('q') == [needle]]
            if matches: return matches[0]
            a.wait_for_timeout(25)
        raise AssertionError('missing count request for selected query')
    def answer(route,count):
        if route.request.failure == 'net::ERR_ABORTED': return
        try: route.fulfill(status=200,content_type='application/json',body=json.dumps({'count':count}))
        except Exception:
            if route.request.failure != 'net::ERR_ABORTED': raise
    stale = search('count-stale-probe')
    expect(indicator).to_have_text('Matching: …')
    expect(a.get_by_role('button',name='Submit feedback',exact=True)).to_be_enabled()
    current = search('count-current-probe')
    replies['count-current-probe'] = (200,'{"count":0}')
    for route in held:
        if parse_qs(urlsplit(route.request.url).query).get('q') == ['count-current-probe']:
            answer(route,0)
    expect(indicator).to_have_text('Matching: 0')
    answer(stale,99); a.wait_for_timeout(100)
    expect(indicator).to_have_text('Matching: 0')
    failed = search('count-error-probe')
    # Keep this deliberately injected outage until recovery, including polls.
    # Every allowed console error is tied to an actual controlled 503 request.
    replies['count-error-probe'] = (503,'{"error":"QA injected failure"}')
    guard.injected(a,failed.request.url)
    failed.fulfill(status=503,content_type='application/json',body='{"error":"QA injected failure"}')
    expect(indicator).to_have_text('Matching unavailable')
    expect(a.get_by_role('button',name='Submit feedback',exact=True)).to_be_enabled()
    expect(a.get_by_label('Title',exact=True)).to_have_value('Count preserved draft')
    for index,value in enumerate(({'count':True},{'count':-1},{'count':1.5},{'count':0,'extra':True},[])):
        needle='count-invalid-probe-'+str(index)
        route=search(needle);body=json.dumps(value);replies[needle]=(200,body)
        route.fulfill(status=200,content_type='application/json',body=body)
        expect(indicator).to_have_text('Matching unavailable')
    a.unroute(COUNT_URL,hold)
    query.fill('Match QA'); query.press('Enter')
    expect(indicator).to_have_text('Matching: 1')
    # Verify refreshed server state, not a local list-length placeholder.
    created = b.request.post(ORIGIN+'/feedback',data={'title':'Match QA third'})
    assert created.status == 201
    expect(indicator).to_have_text('Matching: 2',timeout=6000)
    expect(b.locator('#feedback-match-count')).to_have_text('Matching: 4',timeout=6000)
    return ['count_accessible_status','count_search_filter_composition','count_sort_compatible',
            'count_independent_contexts','count_loading_no_lock','count_stale_response_discarded',
            'count_failure_no_lock','count_draft_preserved','count_invalid_shape_and_types',
            'count_recovers','count_shared_poll_refresh']


def run(scenario):
    if scenario not in ('feedback-board-count-api-v1','feedback-board-count-ui-v1'):
        raise ValueError('count recipe not qualified')
    from playwright.sync_api import sync_playwright,expect
    LAST_ERRORS.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True,args=['--no-sandbox'])
        first, second = browser.new_context(),browser.new_context()
        health = first.request.get(ORIGIN+'/health').json()
        assert health.get('status') == 'ok' and re.fullmatch('[a-f0-9]{40}',health.get('source_sha',''))
        checks = observe_api(first.request)
        page,other = first.new_page(),second.new_page(); guard = ConsoleGuard()
        for current in (page,other):
            current.on('pageerror',lambda error:LAST_ERRORS.append(str(error)))
            current.on('console',lambda msg,current=current:guard.observe(current,msg))
        if scenario.endswith('ui-v1'): checks.extend(observe_ui(page,other,expect,guard))
        else: page.goto(ORIGIN+'/',wait_until='networkidle')
        assert not LAST_ERRORS, 'unexpected count browser errors: '+repr(LAST_ERRORS)
        result = dict(status='passed',source_sha=health['source_sha'],contexts=2,
                      browser_version=browser.version,checks=checks,
                      screenshot_base64=base64.b64encode(page.screenshot(full_page=True)).decode())
        browser.close(); return result


if __name__ == '__main__':
    try: print(json.dumps(run(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'status':'failed','error':type(error).__name__+': '+str(error)}))
        raise SystemExit(1)
