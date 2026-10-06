"""Tiny HTTP harness for the disposable calculator; not product code."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from urllib.parse import parse_qs, urlsplit


def dispatch(path, multiply, square, source_sha, cube=None, negate=None, absolute=None, double=None):
    parsed = urlsplit(path)
    if parsed.path == '/health' and not parsed.query:
        return 200, {'status': 'ok', 'source_sha': source_sha}
    unary = {'/square': square, '/cube': cube, '/negate': negate,
             '/absolute': absolute, '/double': double}
    if parsed.path in unary and unary[parsed.path] is not None:
        values = parse_qs(parsed.query, keep_blank_values=True)
        if set(values) != {'value'} or len(values['value']) != 1:
            return 400, {'error': 'value is required once'}
        try:
            value = int(values['value'][0])
        except ValueError:
            return 400, {'error': 'value must be an integer'}
        if abs(value) > 1_000_000:
            return 400, {'error': 'input out of range'}
        operation = unary[parsed.path]
        return 200, {'result': operation(value), 'source_sha': source_sha}
    if parsed.path != '/multiply':
        return 404, {'error': 'not found'}
    values = parse_qs(parsed.query, keep_blank_values=True)
    if set(values) != {'left', 'right'} or any(len(v) != 1 for v in values.values()):
        return 400, {'error': 'left and right are required once'}
    try:
        left, right = int(values['left'][0]), int(values['right'][0])
    except ValueError:
        return 400, {'error': 'left and right must be integers'}
    if max(abs(left), abs(right)) > 1_000_000:
        return 400, {'error': 'input out of range'}
    return 200, {'result': multiply(left, right), 'source_sha': source_sha}


def main():
    import calc
    multiply, square = calc.multiply, getattr(calc, 'square', None)
    cube, negate = getattr(calc, 'cube', None), getattr(calc, 'negate', None)
    absolute = getattr(calc, 'absolute', None)
    double = getattr(calc, 'double', None)

    source_sha = os.environ['SOURCE_SHA']
    if len(source_sha) != 40 or any(c not in '0123456789abcdef' for c in source_sha):
        raise ValueError('invalid source SHA')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, payload = dispatch(self.path, multiply, square, source_sha,
                                       cube, negate, absolute, double)
            body = json.dumps(payload, sort_keys=True).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


if __name__ == '__main__':
    main()
