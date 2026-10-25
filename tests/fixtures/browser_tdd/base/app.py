"""Discardable capability fixture, not the S4 greeting product."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys

PAGE = b'<!doctype html><button id="increment" type="button">Increment</button><output id="count">0</output>'


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"status":"ok"}' if self.path == '/health' else PAGE
        self.send_response(200)
        self.send_header('Content-Type', 'application/json' if self.path == '/health' else 'text/html')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', int(sys.argv[1])), Handler)
    print(server.server_port, flush=True)
    server.serve_forever()
