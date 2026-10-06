"""Trusted HTTP adapter; agent implements only app.winner."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import json
import os
from urllib.parse import urlparse,parse_qs
from app import winner

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=='/health': code,data=200,dict(status='ok',commit=os.environ['APP_COMMIT'])
        elif parsed.path=='/winner':
            try:
                query=parse_qs(parsed.query,strict_parsing=True)
                if set(query)!={'a','b'} or any(len(v)!=1 for v in query.values()): raise ValueError()
                a,b=int(query['a'][0]),int(query['b'][0])
                if min(a,b)<0 or max(a,b)>1000: raise ValueError()
                code,data=200,dict(winner=winner(a,b),commit=os.environ['APP_COMMIT'])
            except (ValueError,KeyError): code,data=400,dict(error='invalid score')
        else: code,data=404,dict(error='not found')
        raw=json.dumps(data).encode(); self.send_response(code)
        self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

if __name__=='__main__': HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
