"""Fixed causal SPIKE; in-memory intervention is NEVER a product delivery."""
import hashlib
import json
import os
from playwright.sync_api import sync_playwright, expect


def renamed_variant(code):
    substitutions = [('var status =', 'var formStatus ='),
                     ('status.textContent', 'formStatus.textContent'),
                     ('status.classList', 'formStatus.classList')]
    for old, new in substitutions:
        if code.count(old) != 1:
            raise ValueError('fixed historical intervention source drift')
        code = code.replace(old, new, 1)
    return code


def run():
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True, chromium_sandbox=False)
        context = browser.new_context()
        original = context.request.get('http://fixture:8080/static/app.js').text()
        source_hash = hashlib.sha256(original.encode()).hexdigest()
        if source_hash != os.environ['EXPECTED_SCRIPT_SHA256']:
            raise ValueError('deployed JS differs from pinned Git source')
        health = context.request.get('http://fixture:8080/health').json()
        if health['source_sha'] != os.environ['EXPECTED_SOURCE_SHA']:
            raise ValueError('runtime source identity drift')
        baseline = context.new_page()
        errors = []
        posts = []
        baseline.on('pageerror', lambda e: errors.append({'message':str(e),'stack':e.stack}))
        baseline.on('request', lambda r: posts.append(r.url) if r.method=='POST' else None)
        baseline.goto('http://fixture:8080',wait_until='networkidle')
        facts = baseline.evaluate('''() => {
            const node=document.getElementById('form-status');
            const form=document.getElementById('feedback-form');
            return {window_status_type:typeof window.status,
                    window_status_value:window.status,
                    window_status_classList_type:typeof window.status.classList,
                    dom_status_tag:node.tagName, dom_status_classList_type:typeof node.classList,
                    title_name:form.elements.namedItem('title').name,
                    description_name:form.elements.namedItem('description').name};
        }''')
        expect(baseline.locator('#form-status')).to_have_text('')
        baseline.get_by_label('Title',exact=True).fill('Controlled baseline')
        baseline.get_by_role('button',name='Submit feedback',exact=True).click()
        baseline.wait_for_function('typeof window.status === "string"')
        assert facts['title_name']=='title' and facts['description_name']=='description'
        assert facts['window_status_type']=='string'
        assert facts['window_status_classList_type']=='undefined'
        assert facts['dom_status_tag']=='P' and facts['dom_status_classList_type']=='object'
        assert errors and 'setStatus' in errors[0]['stack'] and 'app.js:24:' in errors[0]['stack']
        assert posts==[] and baseline.locator('#form-status').inner_text()==''

        # Explicit intervention: alter ONLY the response body in this fresh
        # browser context. No file, snapshot, test, image, branch or PR changes.
        variant=renamed_variant(original)
        control_context=browser.new_context()
        control_context.route('**/static/app.js',lambda route:route.fulfill(
            status=200,content_type='application/javascript',body=variant))
        control=control_context.new_page()
        control_errors=[]; control_posts=[]
        control.on('pageerror',lambda e:control_errors.append(str(e)))
        control.on('request',lambda r:control_posts.append(r.url) if r.method=='POST' else None)
        control.goto('http://fixture:8080',wait_until='networkidle')
        control.get_by_label('Title',exact=True).fill('Controlled intervention')
        control.get_by_role('button',name='Submit feedback',exact=True).click()
        expect(control.locator('#form-status')).to_have_text('Thanks! Your feedback was added.')
        expect(control.locator('.feedback-title').filter(has_text='Controlled intervention')).to_be_visible()
        assert len(control_posts)==1 and control_errors==[]
        assert context.request.get('http://fixture:8080/static/app.js').text()==original
        result={'status':'causal_spike_passed','scope':'diagnostic_only_not_delivery',
                'source_sha':health['source_sha'],'script_sha256':source_hash,
                'baseline':{'facts':facts,'errors':errors,'posts':len(posts)},
                'intervention':{'kind':'in_memory_response_rename_only',
                                'variant_sha256':hashlib.sha256(variant.encode()).hexdigest(),
                                'posts':len(control_posts),'errors':control_errors,
                                'success_message':control.locator('#form-status').inner_text()},
                'original_source_unchanged':True}
        browser.close()
        return result


if __name__=='__main__':
    print(json.dumps(run()))
