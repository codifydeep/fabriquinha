"""Independent detail QA, composed with the same-SHA legacy regression recipe.

API/UI checks are model-free. Synthetic mutation qualification tests the detector,
not a product delivery. The controller also requires real baseline evidence.
"""
import base64
import json
import re
import sys

ORIGIN = 'http://fixture:8080'
DETAIL_URL = re.compile(re.escape(ORIGIN) + r'/feedback/[1-9][0-9]*(?:\?.*)?$')
LAST_ERRORS = []


class ExpectedDetailFailure:
    """Allow only one console event for the driver's exact injected 503."""
    MESSAGE = 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'

    def __init__(self):
        self.pending = []

    def injected(self, page, url):
        if not DETAIL_URL.fullmatch(url):
            raise AssertionError('exact detail failure URL required')
        self.pending.append((page, url))

    def console(self, page, message, errors):
        if message.type != 'error':
            return
        match = next((i for i, (owner, url) in enumerate(self.pending)
                      if owner is page and url == message.location.get('url')
                      and message.text == self.MESSAGE), None)
        if match is not None:
            self.pending.pop(match)
        else:
            errors.append(message.text)


def exact_json(response, status, expected):
    assert response.status == status, 'unexpected HTTP status'
    assert response.headers.get('content-type', '').split(';', 1)[0].strip() == 'application/json', 'JSON MIME required'
    actual = response.json()
    assert actual == expected, 'unexpected JSON contract'
    # Python equality alone accepts True == 1. Preserve exact JSON types too.
    assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True), 'JSON type drift'
    return actual


def observe_detail_api(request):
    title = '<img src=x onerror=alert(1)> Detail QA'
    created = request.post(ORIGIN + '/feedback', data={
        'title': title, 'description': 'Isolated detail acceptance'})
    assert created.status == 201, 'baseline create contract'
    item = created.json()
    item_id = item['id']
    assert type(item_id) is int and item_id > 0, 'canonical positive item ID'
    expected = {'item': {'id': item_id, 'title': title, 'completed': False}}
    before_list = request.get(ORIGIN + '/feedback').json()
    before_summary = request.get(ORIGIN + '/feedback/summary').json()
    for suffix in ('', '?ignored=1'):
        exact_json(request.get(ORIGIN + '/feedback/' + str(item_id) + suffix), 200, expected)
    exact_json(request.get(ORIGIN + '/feedback/2147483647'), 404, {'error': 'Feedback not found'})
    for token in ('0', '-1', '01', 'letters'):
        exact_json(request.get(ORIGIN + '/feedback/' + token), 400, {'error': 'Invalid feedback id'})
    assert request.get(ORIGIN + '/feedback').json() == before_list, 'detail GET mutated list'
    assert request.get(ORIGIN + '/feedback/summary').json() == before_summary, 'detail GET mutated summary'
    completed = request.post(ORIGIN + '/feedback/' + str(item_id) + '/complete')
    assert completed.status == 200, 'baseline completion contract'
    exact_json(request.get(ORIGIN + '/feedback/' + str(item_id)), 200,
               {'item': {**expected['item'], 'completed': True}})
    return ['detail_exact_json', 'detail_query_compatible', 'detail_not_found',
            'detail_noncanonical_ids', 'detail_read_only', 'detail_literal_title', 'detail_completed_state']


def observe_detail_ui(a, b, request, expect, expected_failures):
    items = []
    for title in ('Detail UI <img src=x onerror=alert(1)> first', 'Detail UI second'):
        created = request.post(ORIGIN + '/feedback', data={'title': title, 'description': 'UI QA fixture'})
        assert created.status == 201, 'UI fixture create failed'
        item = created.json()
        assert type(item['id']) is int and item['id'] > 0, 'positive UI fixture ID'
        items.append({'id': item['id'], 'title': title, 'completed': False})
    held, mutations = [], []
    def capture(route):
        assert route.request.method == 'GET', 'detail must be read-only'
        held.append(route)
    a.route(DETAIL_URL, capture)
    a.on('request', lambda r: mutations.append(r.url) if r.method != 'GET' else None)
    for page in (a, b):
        page.goto(ORIGIN + '/', wait_until='networkidle')
        expect(page.locator('.feedback-item').filter(has_text=items[0]['title'])).to_be_visible()
    a.get_by_label('Title', exact=True).fill('Preserved detail draft')
    a.get_by_label('Description', exact=True).fill('Preserved detail description')
    query = a.get_by_role('searchbox', name='Search feedback', exact=True)
    query.fill('Detail UI'); query.press('Enter')
    a.get_by_role('button', name='Open', exact=True).click()
    a.get_by_role('combobox', name='Sort feedback', exact=True).select_option('oldest')
    def state():
        return a.evaluate('''() => Array.from(document.querySelectorAll(
          'input,textarea,select,[aria-pressed]')).map(e => [e.id,e.value,e.getAttribute('aria-pressed')])''')
    before = state()
    panel = a.locator('#feedback-detail')
    def select(index, keyboard=False):
        button = a.locator('.feedback-item').filter(has_text=items[index]['title']).get_by_role(
            'button', name='View details', exact=True)
        start = len(held)
        if keyboard:
            button.focus(); button.press('Enter')
        else:
            button.click()
        for _ in range(50):
            if len(held) > start: break
            a.wait_for_timeout(50)
        assert len(held) == start + 1, 'exactly one detail fetch per click'
        assert held[-1].request.url.split('?', 1)[0] == ORIGIN+'/feedback/'+str(items[index]['id']), 'wrong detail item URL'
        expect(panel).to_be_visible()
        expect(panel).to_have_attribute('role', 'region')
        expect(panel).to_have_attribute('aria-label', 'Feedback details')
        expect(panel).to_contain_text('Loading details…')
        expect(a.get_by_role('button', name='Submit feedback', exact=True)).to_be_enabled()
        return held[-1]
    def answer(route, index):
        # Aborting a superseded fetch is a valid way to discard stale results.
        if route.request.failure == 'net::ERR_ABORTED': return
        try:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({'item': items[index]}))
        except Exception:
            if route.request.failure != 'net::ERR_ABORTED': raise
    def visible(index):
        expect(panel).to_contain_text(items[index]['title'])
        expect(panel).to_contain_text('Open')
        expect(panel.locator('img,script,iframe')).to_have_count(0)
        assert state() == before, 'detail changed draft or board controls'
    route = select(0, keyboard=True); answer(route, 0); visible(0)
    a.get_by_role('button', name='Close details', exact=True).click()
    expect(panel).not_to_be_visible()
    assert state() == before, 'closing detail changed board state'
    # Two ordinary contexts share data, never local panel state.
    b.locator('.feedback-item').filter(has_text=items[1]['title']).get_by_role(
        'button', name='View details', exact=True).click()
    expect(b.locator('#feedback-detail')).to_contain_text(items[1]['title'])
    b.locator('.feedback-item').filter(has_text='<img src=x onerror=alert(1)> Detail QA').get_by_role(
        'button', name='View details', exact=True).click()
    expect(b.locator('#feedback-detail')).to_contain_text('Completed')
    expect(panel).not_to_be_visible()
    route = select(0)
    expected_failures.injected(a, route.request.url)
    route.fulfill(status=503, content_type='application/json', body='{"error":"QA injected failure"}')
    expect(panel).to_contain_text('Details unavailable')
    expect(a.get_by_role('button', name='Submit feedback', exact=True)).to_be_enabled()
    assert state() == before, 'failed detail changed board state'
    stale = select(0); current = select(1)
    answer(current, 1); visible(1); answer(stale, 0)
    a.wait_for_timeout(100); visible(1)
    pending = select(0)
    a.get_by_role('button', name='Close details', exact=True).click()
    answer(pending, 0); a.wait_for_timeout(100)
    expect(panel).not_to_be_visible()
    assert state() == before, 'pending-close changed board state'
    assert not mutations, 'detail triggered a write request'
    count = len(held)
    a.wait_for_timeout(2200)
    assert len(held) == count, 'detail added polling'
    a.unroute(DETAIL_URL, capture)
    return ['detail_accessible_panel', 'detail_loading', 'detail_keyboard', 'detail_one_fetch',
            'detail_literal_html', 'detail_close_preserves_board', 'detail_two_contexts', 'detail_completed_ui',
            'detail_failure_no_form_lock', 'detail_stale_selection', 'detail_pending_close',
            'detail_no_mutations_or_polling']


def run(scenario):
    if scenario not in ('feedback-board-detail-api-v1', 'feedback-board-detail-ui-v1'):
        raise ValueError('detail recipe not qualified')
    from playwright.sync_api import sync_playwright, expect
    LAST_ERRORS.clear()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        first, second = browser.new_context(), browser.new_context()
        health = first.request.get(ORIGIN + '/health').json()
        assert health.get('status') == 'ok' and re.fullmatch('[a-f0-9]{40}', health.get('source_sha', '')), 'health identity'
        checks = observe_detail_api(first.request)
        assert second.request.get(ORIGIN + '/feedback').json() == first.request.get(ORIGIN + '/feedback').json(), 'independent contexts'
        page, other = first.new_page(), second.new_page()
        failures = ExpectedDetailFailure()
        for current in (page, other):
            current.on('pageerror', lambda error: LAST_ERRORS.append(str(error)))
            current.on('console', lambda message, current=current: failures.console(current, message, LAST_ERRORS))
        if scenario == 'feedback-board-detail-ui-v1':
            checks.extend(observe_detail_ui(page, other, first.request, expect, failures))
        else:
            page.goto(ORIGIN + '/', wait_until='networkidle')
        assert not LAST_ERRORS, 'browser errors: ' + repr(LAST_ERRORS)
        screenshot = base64.b64encode(page.screenshot(full_page=True)).decode()
        result = {'status': 'passed', 'source_sha': health['source_sha'], 'contexts': 2,
                  'browser_version': browser.version, 'checks': checks,
                  'screenshot_base64': screenshot}
        browser.close()
        return result


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1])))
    except Exception as error:
        print(json.dumps({'status': 'failed', 'error': type(error).__name__ + ': ' + str(error)
                         + (' Browser runtime errors: '+repr(LAST_ERRORS) if LAST_ERRORS else '')}))
        raise SystemExit(1)
