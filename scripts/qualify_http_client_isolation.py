"""Run inside the qualified browser image, with no external network.

Generic diagnostic only: does not execute a product or grant delivery approval.
"""
import json, threading, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from playwright.sync_api import sync_playwright
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        status=409 if self.path=='/conflict' else 204 if self.path=='/favicon.ico' else 200
        self.send_response(status);self.send_header('Content-Type','text/html');self.end_headers()
        if status!=204:self.wfile.write(b'<!doctype html><title>Client isolation probe</title>')
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
origin='http://127.0.0.1:'+str(server.server_port)
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page();errors=[]
        page.on('console',lambda msg:errors.append(msg.text) if msg.type=='error' else None)
        page.goto(origin)
        try:urllib.request.urlopen(origin+'/conflict')
        except urllib.error.HTTPError as error:python_status=error.code
        page.wait_for_timeout(200)
        python_errors=list(errors)
        browser_status=page.evaluate("async () => (await fetch('/conflict')).status")
        page.wait_for_timeout(200)
        result=dict(python_status=python_status,console_errors_after_python=python_errors,
                    browser_status=browser_status,console_errors_after_browser=list(errors),
                    delivery_approval=False,scope='Generic HTTP client isolation; no product execution or quality approval')
        assert python_status==409 and python_errors==[]
        assert browser_status==409 and errors
        print(json.dumps(result));browser.close()
finally:server.shutdown();server.server_close()
