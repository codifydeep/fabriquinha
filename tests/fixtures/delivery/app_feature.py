"""Deterministic reference for gate qualification only, not an agent delivery."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys
from urllib.parse import parse_qs, urlsplit

PAGE = b'''<!doctype html><html lang="en"><title>Greeting</title>
<label>Name <input id="name" value="Ada"></label><button id="greet">Greet</button>
<p id="result" role="status"></p><script>
document.querySelector('#greet').onclick=async()=>{
 const r=await fetch('/greeting?name='+encodeURIComponent(document.querySelector('#name').value));
 document.querySelector('#result').textContent=(await r.json()).message;
};</script></html>'''


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        status, value = 404, {'error': 'not found'}
        if url.path == '/health':
            status, value = 200, {'status': 'ok'}
        elif url.path == '/identity':
            status, value = 200, {'source_sha': os.environ.get('FABRIQUINHA_SOURCE_SHA', '')}
        elif url.path == '/greeting':
            status, value = 200, {'message': 'Hello, '+parse_qs(url.query).get('name', ['World'])[0]}
        elif url.path == '/':
            status, value = 200, PAGE
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8' if isinstance(value, bytes) else 'application/json')
        self.end_headers()
        self.wfile.write(value if isinstance(value, bytes) else json.dumps(value).encode())

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', int(sys.argv[1])), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
