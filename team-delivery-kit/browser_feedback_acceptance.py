"""Trusted feedback-board scenario, executed only inside the isolated QA browser."""
import base64
import json
import re
import sys
from playwright.sync_api import sync_playwright, expect

LAST_ERRORS = []


class ExpectedServiceFailure:
    """One console event, bound to an actual driver-injected response."""
    URL = 'http://fixture:8080/service-mode'
    MESSAGE = 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)'

    def __init__(self):
        self.pending = []

    def injected(self, page, url, status):
        if url != self.URL or status != 503:
            raise AssertionError('exact injected service-mode failure required')
        self.pending.append(page)

    def console(self, page, message):
        if message.type != 'error':
            return
        if (message.text == self.MESSAGE and message.location.get('url') == self.URL
                and any(item is page for item in self.pending)):
            index = next(i for i, item in enumerate(self.pending) if item is page)
            self.pending.pop(index)
            return
        record_browser_error(message.text)

    def finish(self, page):
        self.pending = [item for item in self.pending if item is not page]


def record_browser_error(message):
    if len(LAST_ERRORS) < 8:
        text = str(message)
        stack = getattr(message, 'stack', None)
        if isinstance(stack, str) and stack:
            text += ' Stack: ' + stack
        LAST_ERRORS.append(text[:500])


def failure_output(error):
    # Preserve runtime failures even when an earlier locator assertion aborts
    # the scenario before its final no-browser-errors assertion.
    runtime = 'Browser runtime errors: ' + json.dumps(LAST_ERRORS) + '. ' if LAST_ERRORS else ''
    return {'status': 'failed', 'error': runtime + type(error).__name__ + ': ' + str(error)}


def observe_filtered_submission(page, title, *, selected, choose, expect):
    # Keep Completed after POST; only the driver may subsequently select All.
    selected(page, 'Completed')
    item = page.locator('.feedback-title').filter(has_text=title)
    expect(item).to_have_count(0)
    choose(page, 'All')
    expect(item).to_be_visible()


def observe_same_view_generation(page, expect):
    held=[]
    def capture(route):
        if route.request.method=='GET' and route.request.url.split('?',1)[0].endswith('/feedback') and len(held)<2:
            held.append(route)
        else:route.continue_()
    # Earlier checks exercise real polling. This final race must control only
    # its two requests: pause the exact intervals recorded before app startup,
    # drain a genuine refresh, then restore intervals after observation.
    page.evaluate('''() => {
      if (!window.__deliveryQaIntervals) throw new Error('timer registry required');
      window.__deliveryQaIntervals.forEach(t => clearInterval(t.id));
    }''')
    page.evaluate('() => loadFeedback()')
    page.route('**/feedback*',capture)
    try:
        page.evaluate('''() => {
          window.__deliveryGenerationQa = { oldDone:false, newDone:false };
          loadFeedback().then(() => { window.__deliveryGenerationQa.oldDone=true; });
          loadFeedback().then(() => { window.__deliveryGenerationQa.newDone=true; });
        }''')
        page.evaluate('() => 0')
        assert len(held)==2, 'two held real board GETs required'
        assert held[0].request.url==held[1].request.url, 'identical view required'
        held[1].fulfill(status=200,content_type='application/json',body=json.dumps(
            {'items':[{'id':9002,'title':'CURRENT generation QA','completed':False}]}))
        page.wait_for_function('window.__deliveryGenerationQa.newDone === true')
        expect(page.locator('.feedback-title')).to_have_text(['CURRENT generation QA'])
        held[0].fulfill(status=200,content_type='application/json',body=json.dumps(
            {'items':[{'id':9001,'title':'STALE generation QA','completed':False}]}))
        page.wait_for_function('window.__deliveryGenerationQa.oldDone === true')
        expect(page.locator('.feedback-title')).to_have_text(['CURRENT generation QA'])
    finally:
        page.unroute('**/feedback*',capture)
        page.evaluate('''() => {
          const intervals=window.__deliveryQaIntervals.splice(0);
          intervals.forEach(t => setInterval(t.callback,t.delay,...t.args));
        }''')


def observe_service_status_api(context):
    for path in ('/service-status', '/service-status?probe=1'):
        response = context.request.get('http://fixture:8080' + path)
        assert response.status == 200, 'service status HTTP response required'
        assert response.json() == {'status': 'available'}, 'exact service availability contract required'
        assert response.headers.get('content-type', '').startswith('application/json')


def observe_service_status_ui(a, b, expect):
    for page in (a, b):
        expect(page.locator('#service-status')).to_have_text('Service available')
        expect(page.locator('#service-status')).to_have_attribute('role', 'status')
    held = []
    def hold(route):
        held.append(route)
    b.route('**/service-status', hold)
    try:
        with b.expect_request('**/service-status'):
            b.reload(wait_until='domcontentloaded')
        b.wait_for_function("document.querySelector('#service-status').textContent === 'Checking service…'")
        assert len(held) == 1, 'one real startup service GET required'
        b.get_by_label('Title', exact=True).fill('Service probe draft')
        held[0].fulfill(status=200, content_type='application/json', body='{"status":"available"}')
        expect(b.locator('#service-status')).to_have_text('Service available')
        expect(b.get_by_label('Title', exact=True)).to_have_value('Service probe draft')
    finally:
        b.unroute('**/service-status', hold)
    def invalid(route):
        route.fulfill(status=200, content_type='application/json', body='{"status":"unknown"}')
    b.route('**/service-status', invalid)
    try:
        b.reload(wait_until='domcontentloaded')
        expect(b.locator('#service-status')).to_have_text('Service unavailable')
        expect(b.get_by_role('button', name='Submit feedback', exact=True)).to_be_enabled()
        expect(a.locator('#service-status')).to_have_text('Service available')
    finally:
        b.unroute('**/service-status', invalid)


def observe_demo_mode_api(context):
    for path in ('/service-mode','/service-mode?probe=1'):
        response=context.request.get('http://fixture:8080'+path)
        assert response.status==200, 'demo-mode HTTP response required'
        assert response.json()=={'mode':'demo'}, 'exact demo-mode JSON required'
        assert response.headers.get('content-type','').startswith('application/json')


def observe_demo_mode_ui(a,b,expect,expected_failures):
    for page in (a,b):
        expect(page.locator('#service-mode')).to_have_text('Demo environment')
        expect(page.locator('#service-mode')).to_have_attribute('role','status')
    held=[]
    def hold(route):held.append(route)
    b.route('**/service-mode',hold)
    try:
        with b.expect_request('**/service-mode'):b.reload(wait_until='domcontentloaded')
        expect(b.locator('#service-mode')).to_have_text('Checking environment…')
        assert len(held)==1, 'one startup demo-mode request required'
        b.get_by_label('Title',exact=True).fill('Demo probe draft')
        held[0].fulfill(status=200,content_type='application/json',body='{"mode":"demo"}')
        expect(b.locator('#service-mode')).to_have_text('Demo environment')
        expect(b.get_by_label('Title',exact=True)).to_have_value('Demo probe draft')
    finally:b.unroute('**/service-mode',hold)
    for body,status in [('not-json',200),('{"mode":"demo","extra":true}',200),('{"mode":"demo"}',503)]:
        def invalid(route):
            if status == 503:
                expected_failures.injected(b, route.request.url, status)
            route.fulfill(status=status,content_type='application/json',body=body)
        b.route('**/service-mode',invalid)
        try:
            b.reload(wait_until='domcontentloaded')
            expect(b.locator('#service-mode')).to_have_text('Environment unavailable')
            expect(b.get_by_role('button',name='Submit feedback',exact=True)).to_be_enabled()
            expect(a.locator('#service-mode')).to_have_text('Demo environment')
        finally:
            b.unroute('**/service-mode',invalid)
            expected_failures.finish(b)


def run(scenario='feedback-board-v1'):
    if scenario not in ('feedback-board-v1', 'feedback-board-pending-v1',
                        'feedback-board-pending-accessibility-v1',
                        'feedback-board-keyboard-dismiss-v1',
                        'feedback-board-status-filter-api-v1', 'feedback-board-filter-v1',
                        'feedback-board-sort-v1', 'feedback-board-search-api-v1',
                        'feedback-board-search-v1', 'feedback-board-search-generation-v1',
                        'feedback-board-service-status-api-v1', 'feedback-board-service-status-ui-v1',
                        'feedback-board-demo-mode-api-v1', 'feedback-board-demo-mode-ui-v1'):
        raise ValueError('unsupported fixed scenario')
    demo_api=scenario in ('feedback-board-demo-mode-api-v1','feedback-board-demo-mode-ui-v1')
    demo_ui=scenario=='feedback-board-demo-mode-ui-v1'
    service_api = scenario in ('feedback-board-service-status-api-v1', 'feedback-board-service-status-ui-v1') or demo_api
    service_ui = scenario == 'feedback-board-service-status-ui-v1' or demo_api
    generation = scenario == 'feedback-board-search-generation-v1' or service_api
    searching = scenario == 'feedback-board-search-v1' or generation
    api_search = searching or scenario == 'feedback-board-search-api-v1'
    sorting = api_search or scenario == 'feedback-board-sort-v1'
    filtering = sorting or scenario == 'feedback-board-filter-v1'
    api_filter = filtering or scenario == 'feedback-board-status-filter-api-v1'
    keyboard = api_filter or scenario == 'feedback-board-keyboard-dismiss-v1'
    accessible = scenario in ('feedback-board-pending-accessibility-v1',
                              'feedback-board-keyboard-dismiss-v1') or api_filter
    pending = scenario != 'feedback-board-v1'
    LAST_ERRORS.clear()
    errors = LAST_ERRORS
    expected_failures = ExpectedServiceFailure()
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, chromium_sandbox=False)
        first = browser.new_context()
        second = browser.new_context()
        pages = [first.new_page(), second.new_page()]
        for page in pages:
            page.set_default_timeout(10000)
            page.on('pageerror', record_browser_error)
            page.on('console', lambda message, page=page: expected_failures.console(page, message))
        a, b = pages
        if generation:
            a.add_init_script('''(() => {
              const nativeSetInterval=window.setInterval.bind(window);
              window.__deliveryQaIntervals=[];
              window.setInterval=(callback,delay,...args) => {
                const id=nativeSetInterval(callback,delay,...args);
                window.__deliveryQaIntervals.push({id,callback,delay,args});
                return id;
              };
            })();''')
        def filter_control(page, name):
            for role in ('button', 'tab', 'radio'):
                item = page.get_by_role(role, name=name, exact=True).and_(page.locator(':not(.complete-button)'))
                if item.count() == 1:
                    return item, role
            for item in page.get_by_role('combobox').all():
                if item.get_by_role('option', name=name, exact=True).count() == 1:
                    return item, 'combobox'
            raise AssertionError('accessible filter control not found: ' + name)

        def selected(page, name):
            item, role = filter_control(page, name)
            if role == 'combobox':
                expect(item.locator('option:checked')).to_have_text(name)
            elif role == 'radio':
                expect(item).to_be_checked()
            else:
                attribute = 'aria-selected' if role == 'tab' else 'aria-pressed'
                expect(item).to_have_attribute(attribute, 'true')

        def choose(page, name):
            item, role = filter_control(page, name)
            if role == 'combobox':
                item.select_option(label=name)
            elif role == 'radio':
                item.check()
            else:
                item.click()
            selected(page, name)
        post_counts = {a: 0, b: 0}
        if pending:
            def intercept(route):
                page = route.request.frame.page
                if route.request.method == 'POST':
                    post_counts[page] += 1
                    # Inspect the UI while the real request is held. Force a
                    # second submit event: disabling a button alone is not a guard.
                    button = page.get_by_role('button', name='Submit feedback', exact=True)
                    if not button.is_disabled():
                        errors.append('submit button remained enabled during POST')
                    if accessible and page.locator('#feedback-form').get_attribute('aria-busy') != 'true':
                        errors.append('form did not announce busy during POST')
                    if keyboard:
                        page.get_by_label('Title', exact=True).press('Escape')
                        expect(page.locator('#form-status')).to_have_text('Submitting...')
                        expect(page.locator('#feedback-form')).to_have_attribute('aria-busy', 'true')
                        expect(button).to_be_disabled()
                    if sorting and post_counts[page] == 1:
                        order=page.get_by_role('combobox',name='Sort feedback',exact=True)
                        draft=page.get_by_label('Title',exact=True).input_value()
                        order.select_option(label='Oldest first')
                        expect(page.get_by_label('Title',exact=True)).to_have_value(draft)
                        expect(page.locator('#feedback-form')).to_have_attribute('aria-busy','true')
                        expect(button).to_be_disabled()
                        order.select_option(label='Newest first')
                    if filtering and post_counts[page] == 1:
                        # Real POST is held. Switching filter is permitted by
                        # the brief, but must preserve draft and submission guard.
                        draft_title = page.get_by_label('Title', exact=True).input_value()
                        draft_description = page.get_by_label('Description', exact=True).input_value()
                        item, role = filter_control(page, 'Completed')
                        if role == 'combobox':
                            item.select_option(label='Completed')
                        elif role == 'radio':
                            item.check()
                        else:
                            item.evaluate("el => el.dispatchEvent(new MouseEvent('click', {bubbles:true}))")
                        selected(page, 'Completed')
                        expect(page.get_by_label('Title', exact=True)).to_have_value(draft_title)
                        expect(page.get_by_label('Description', exact=True)).to_have_value(draft_description)
                        expect(page.locator('#form-status')).to_have_text('Submitting...')
                        expect(page.locator('#feedback-form')).to_have_attribute('aria-busy', 'true')
                        expect(button).to_be_disabled()
                    if post_counts[page] == 1:
                        page.evaluate("document.getElementById('feedback-form').dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))")
                route.continue_()
            for page in pages:
                page.route('**/feedback', intercept)
        for page in pages:
            response = page.goto('http://fixture:8080', wait_until='networkidle')
            assert response.status == 200
            if accessible:
                expect(page.locator('#feedback-form')).to_have_attribute('aria-busy', 'false')
            if filtering:
                selected(page, 'All')
            if sorting:
                expect(page.get_by_role('combobox', name='Sort feedback', exact=True)
                       .locator('option:checked')).to_have_text('Newest first')
        health = first.request.get('http://fixture:8080/health').json()

        def counts(page, total, opened, completed):
            for selector, value in (('#summary-total', total), ('#summary-open', opened),
                                    ('#summary-completed', completed)):
                expect(page.locator(selector)).to_have_text(str(value))

        def submit(page, title):
            page.get_by_label('Title', exact=True).fill(title)
            page.get_by_label('Description', exact=True).fill('Isolated acceptance fixture')
            page.get_by_role('button', name='Submit feedback', exact=True).click()
            expect(page.locator('#form-status')).to_have_text('Thanks! Your feedback was added.')
            if filtering:
                observe_filtered_submission(page, title, selected=selected, choose=choose, expect=expect)
            else:
                expect(page.locator('.feedback-title').filter(has_text=title)).to_be_visible()
            if pending:
                expect(page.get_by_role('button', name='Submit feedback', exact=True)).to_be_enabled()
                assert post_counts[page] == 1, 'duplicate in-flight POST'
            if accessible:
                expect(page.locator('#feedback-form')).to_have_attribute('aria-busy', 'false')

        counts(a, 0, 0, 0)
        if accessible:
            a.get_by_label('Title', exact=True).fill('   ')
            a.get_by_role('button', name='Submit feedback', exact=True).click()
            expect(a.locator('#form-status')).to_have_text('Please enter a title before submitting.')
            expect(a.locator('#feedback-form')).to_have_attribute('aria-busy', 'false')
            expect(a.get_by_role('button', name='Submit feedback', exact=True)).to_be_enabled()
            assert post_counts[a] == 0, 'invalid title generated a POST'
            if keyboard:
                a.get_by_label('Description', exact=True).fill('Keep this draft')
                a.get_by_label('Title', exact=True).press('ArrowLeft')
                expect(a.locator('#form-status')).to_have_text('Please enter a title before submitting.')
                a.get_by_label('Title', exact=True).press('Escape')
                expect(a.locator('#form-status')).to_have_text('')
                expect(a.locator('#form-status')).not_to_have_class(re.compile(r'\bis-error\b'))
                expect(a.get_by_label('Title', exact=True)).to_have_value('   ')
                expect(a.get_by_label('Description', exact=True)).to_have_value('Keep this draft')
                assert post_counts[a] == 0, 'Escape generated a POST'
        submit(a, 'Browser acceptance first')
        counts(a, 1, 1, 0)
        a.get_by_role('button', name='Mark complete', exact=True).click()
        expect(a.locator('#feedback-list').get_by_role('button', name='Completed', exact=True)).to_be_disabled()
        counts(a, 1, 0, 1)
        submit(b, 'Browser acceptance second')
        counts(b, 2, 1, 1)
        # No reload: the original session must converge through application polling.
        counts(a, 2, 1, 1)
        expect(a.locator('.feedback-title').filter(has_text='Browser acceptance second')).to_be_visible()
        if api_filter:
            for state, expected_title in (('open', 'Browser acceptance second'),
                                          ('completed', 'Browser acceptance first')):
                response = first.request.get('http://fixture:8080/feedback?status=' + state)
                assert response.status == 200
                body = response.json()
                assert isinstance(body, dict) and isinstance(body.get('items'), list), 'preserve baseline items envelope'
                rows = body['items']
                assert len(rows) == 1 and rows[0]['title'] == expected_title
            for value in ('', 'all', 'unknown'):
                response = first.request.get('http://fixture:8080/feedback?status=' + value)
                assert response.status == 400, 'invalid explicit filter must be rejected'
                assert 'application/json' in response.headers.get('content-type', '')
                assert isinstance(response.json(), dict), 'API error must be JSON object'
            response = first.request.get('http://fixture:8080/feedback')
            assert response.status == 200 and len(response.json()['items']) == 2
            assert first.request.get('http://fixture:8080/feedback/summary?status=open').json() == {
                'total': 2, 'open': 1, 'completed': 1}
        if filtering:
            a.get_by_label('Title', exact=True).fill('Keep filter draft')
            a.get_by_label('Description', exact=True).fill('Keep filter description')
            choose(a, 'Open')
            choose(b, 'Completed')
            expect(a.locator('.feedback-title')).to_have_text(['Browser acceptance second'])
            expect(b.locator('.feedback-title')).to_have_text(['Browser acceptance first'])
            expect(a.get_by_label('Title', exact=True)).to_have_value('Keep filter draft')
            expect(a.get_by_label('Description', exact=True)).to_have_value('Keep filter description')
            counts(a, 2, 1, 1)
            counts(b, 2, 1, 1)
            # External fixture mutation proves polling without reload, while
            # the two contexts keep different view state and whole-board counts.
            response = first.request.post('http://fixture:8080/feedback', data={
                'title': 'Filter polling third', 'description': 'Fixture mutation'})
            assert response.status in (200, 201)
            expect(a.locator('.feedback-title').filter(has_text='Filter polling third')).to_be_visible()
            counts(a, 3, 2, 1)
            counts(b, 3, 2, 1)
            selected(a, 'Open')
            selected(b, 'Completed')
            expect(b.locator('.feedback-title')).to_have_text(['Browser acceptance first'])
            expect(a.get_by_label('Title', exact=True)).to_have_value('Keep filter draft')
            a.get_by_label('Title', exact=True).fill('Filter creation fourth')
            a.get_by_role('button', name='Submit feedback', exact=True).click()
            expect(a.locator('#form-status')).to_have_text('Thanks! Your feedback was added.')
            selected(a, 'Open')
            expect(a.locator('.feedback-title').filter(has_text='Filter creation fourth')).to_be_visible()
            counts(a, 4, 3, 1)
            counts(b, 4, 3, 1)
            assert post_counts[a] == 2, 'filter interaction caused duplicate POST'
            for title in ('Browser acceptance second', 'Filter polling third', 'Filter creation fourth'):
                row = a.locator('.feedback-item').filter(has_text=title)
                row.get_by_role('button', name='Mark complete', exact=True).click()
                expect(row).to_have_count(0)
                selected(a, 'Open')
            counts(a, 4, 0, 4)
            expect(a.locator('#empty-state')).to_be_visible()
            expect(a.locator('#empty-state')).to_contain_text(re.compile(r'open', re.I))
            selected(b, 'Completed')
            counts(b, 4, 0, 4)
            expect(b.locator('.feedback-title')).to_have_count(4)
            choose(a, 'All')
            expect(a.locator('.feedback-title')).to_have_count(4)
        if sorting:
            # Creation order is the stable numeric feedback ID, not wall-clock
            # timestamps or the input array's incidental order.
            oldest=['Browser acceptance first','Browser acceptance second',
                    'Filter polling third','Filter creation fourth']
            choose(b,'All')
            order_a=a.get_by_role('combobox',name='Sort feedback',exact=True)
            order_b=b.get_by_role('combobox',name='Sort feedback',exact=True)
            expect(a.locator('.feedback-title')).to_have_text(list(reversed(oldest)))
            order_b.select_option(label='Oldest first')
            expect(b.locator('.feedback-title')).to_have_text(oldest)
            expect(order_a.locator('option:checked')).to_have_text('Newest first')
            a.get_by_label('Title',exact=True).fill('Preserved sort draft')
            a.get_by_label('Description',exact=True).fill('Preserved sort description')
            order_a.select_option(label='Oldest first')
            expect(a.locator('.feedback-title')).to_have_text(oldest)
            expect(a.get_by_label('Title',exact=True)).to_have_value('Preserved sort draft')
            expect(a.get_by_label('Description',exact=True)).to_have_value('Preserved sort description')
            order_a.focus()
            order_a.press('Home')
            expect(order_a.locator('option:checked')).to_have_text('Newest first')
            expect(a.locator('.feedback-title')).to_have_text(list(reversed(oldest)))
            response=first.request.post('http://fixture:8080/feedback',data={
                'title':'Sort polling fifth','description':'Fixture mutation'})
            assert response.status in (200,201)
            expect(a.locator('.feedback-title')).to_have_text(['Sort polling fifth']+list(reversed(oldest)))
            expect(b.locator('.feedback-title')).to_have_text(oldest+['Sort polling fifth'])
            counts(a,5,1,4);counts(b,5,1,4)
            choose(a,'Open')
            expect(a.locator('.feedback-title')).to_have_text(['Sort polling fifth'])
            expect(order_a.locator('option:checked')).to_have_text('Newest first')
            choose(a,'All')
            row=a.locator('.feedback-item').filter(has_text='Sort polling fifth')
            row.get_by_role('button',name='Mark complete',exact=True).click()
            expect(row.get_by_role('button',name='Completed',exact=True)).to_be_disabled()
            expect(a.locator('.feedback-title')).to_have_text(['Sort polling fifth']+list(reversed(oldest)))
            counts(a,5,0,5);counts(b,5,0,5)
            expect(order_b.locator('option:checked')).to_have_text('Oldest first')
            expect(b.locator('.feedback-title')).to_have_text(oldest+['Sort polling fifth'])
        if api_search:
            found = first.request.get('http://fixture:8080/feedback?q=%20POLLING%20')
            assert found.status == 200
            body = found.json()
            # Preserve the existing API envelope, which the actual client uses.
            records = body if isinstance(body, list) else body['items']
            assert records and all('polling' in item['title'].casefold() for item in records)
            missing = first.request.get('http://fixture:8080/feedback?q=absent-needle-6281').json()
            assert (missing if isinstance(missing, list) else missing['items']) == []
            absent = first.request.get('http://fixture:8080/feedback').json()
            blank = first.request.get('http://fixture:8080/feedback?q=%20%20').json()
            assert blank == absent
            summary = first.request.get('http://fixture:8080/feedback/summary').json()
            assert first.request.get('http://fixture:8080/feedback/summary?q=absent').json() == summary
        if searching:
            query = a.get_by_role('searchbox', name='Search feedback', exact=True)
            query_b = b.get_by_role('searchbox', name='Search feedback', exact=True)
            expect(query).to_have_value('')
            a.get_by_label('Title', exact=True).fill('Search preserved draft')
            query.fill(' POLLING ')
            query.press('Enter')
            expect(a.locator('.feedback-title')).to_have_text(['Sort polling fifth', 'Filter polling third'])
            expect(query_b).to_have_value('')
            expect(b.locator('.feedback-title')).to_have_count(5)
            expect(a.get_by_label('Title', exact=True)).to_have_value('Search preserved draft')
            query.fill('absent-needle-6281')
            query.press('Enter')
            expect(a.locator('.feedback-title')).to_have_count(0)
            query.fill('')
            query.press('Enter')
            expect(a.locator('.feedback-title')).to_have_count(5)
            counts(a,5,0,5)
        if generation:
            observe_same_view_generation(a,expect)
        if service_api:
            observe_service_status_api(first)
        if service_ui:
            observe_service_status_ui(a, b, expect)
        if demo_api:observe_demo_mode_api(first)
        if demo_ui:observe_demo_mode_ui(a,b,expect,expected_failures)
        assert not errors, 'browser errors: ' + repr(errors)
        screenshot = base64.b64encode(a.screenshot(full_page=True)).decode()
        result = {'status': 'passed', 'source_sha': health['source_sha'],
                  'browser_version': browser.version, 'contexts': 2,
                  'checks': ['initial_empty', 'create', 'complete', 'second_user',
                             'poll_without_reload', 'no_browser_errors'],
                  'screenshot_base64': screenshot}
        if pending:
            result['checks'].append('pending_button_and_duplicate_guard')
        if api_search:
            result['checks'].extend(['search_api_trim_casefold', 'search_api_missing',
                                    'search_api_blank_compatible', 'search_summary_whole_board'])
        if searching:
            result['checks'].extend(['search_enter', 'search_independent_context',
                                    'search_draft_preserved', 'search_empty_and_clear'])
        if generation:
            result['checks'].append('same_view_stale_request_generation_discarded')
        if service_api:
            result['checks'].extend(['service_status_exact_http', 'service_status_query_compatible'])
        if service_ui:
            result['checks'].extend(['service_status_two_contexts', 'service_status_pending',
                                    'service_status_draft_preserved', 'service_status_invalid_response',
                                    'service_status_no_form_lock'])
        if demo_api:result['checks'].extend(['demo_mode_exact_http','demo_mode_query_compatible'])
        if demo_ui:result['checks'].extend(['demo_mode_two_contexts','demo_mode_pending',
            'demo_mode_draft_preserved','demo_mode_invalid_json','demo_mode_extra_fields',
            'demo_mode_non200','demo_mode_no_form_lock'])
        if accessible:
            result['checks'].extend(['aria_busy_initial_and_settled',
                                    'aria_busy_during_post', 'invalid_title_never_busy'])
        if keyboard:
            result['checks'].extend(['escape_dismisses_idle_status_preserving_draft',
                                    'unrelated_key_preserves_status',
                                    'escape_does_not_cancel_pending_submission'])
        if api_filter:
            result['checks'].extend(['api_open_completed_filter', 'api_invalid_explicit_status',
                                    'api_default_and_summary_compatible'])
        if filtering:
            result['checks'].extend(['filters_default_and_switch', 'filter_draft_preserved',
                                    'filters_two_browser_independence', 'filtered_poll_without_reload',
                                    'filter_survives_create_complete', 'filtered_empty_state',
                                    'filter_during_pending_keeps_post_guard'])
        if sorting:
            result['checks'].extend(['sort_default_newest', 'sort_oldest_numeric_id',
                                    'sort_two_browser_independence','sort_draft_preserved',
                                    'sort_keyboard_control','sort_poll_without_reload',
                                    'sort_composes_with_filter','sort_survives_completion',
                                    'sort_during_pending_keeps_post_guard'])
        browser.close()
        return result


if __name__ == '__main__':
    try:
        print(json.dumps(run(sys.argv[1] if len(sys.argv) > 1 else 'feedback-board-v1')))
    except Exception as error:
        print(json.dumps(failure_output(error)))
        raise SystemExit(1)
