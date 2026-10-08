"""Draft isolated detail QA; not admitted by the fixed recipe registry yet.

API checks are model-free. UI/race checks and same-SHA baseline composition must
be qualified before this recipe can become an executable delivery gate.
"""
import base64
import json
import re
import sys

ORIGIN = 'http://fixture:8080'


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
    return ['detail_exact_json', 'detail_query_compatible', 'detail_not_found',
            'detail_noncanonical_ids', 'detail_read_only', 'detail_literal_title']


def run(scenario):
    if scenario != 'feedback-board-detail-api-v1':
        raise ValueError('detail UI recipe not qualified')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=['--no-sandbox'])
        first, second = browser.new_context(), browser.new_context()
        health = first.request.get(ORIGIN + '/health').json()
        assert health.get('status') == 'ok' and re.fullmatch('[a-f0-9]{40}', health.get('source_sha', '')), 'health identity'
        checks = observe_detail_api(first.request)
        assert second.request.get(ORIGIN + '/feedback').json() == first.request.get(ORIGIN + '/feedback').json(), 'independent contexts'
        page = first.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)
        page.goto(ORIGIN + '/', wait_until='networkidle')
        assert not errors, 'browser errors: ' + repr(errors)
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
        print(json.dumps({'status': 'failed', 'error': type(error).__name__ + ': ' + str(error)}))
        raise SystemExit(1)
