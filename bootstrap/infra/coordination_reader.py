"""Fixed read-only receipt API. Only this service may create SQLite sidecars."""
import json
import os
from pathlib import Path
import socket
import socketserver
import sqlite3

SOCKET='/run/coordination-read/reader.sock'

def read_receipts(path,attempt,request):
    if request!={'operation':'recovery_receipts','attempt':attempt}:
        raise PermissionError('fixed attempt-scoped read operation only')
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        def record(kind,item):
            row=db.execute('SELECT data FROM records WHERE attempt=? AND kind=? AND id=?',(attempt,kind,item)).fetchone()
            return json.loads(row[0]) if row else None
        sent=db.execute('SELECT sent_at FROM outbox WHERE attempt=? AND id=?',(attempt,'e2e-outbox-probe')).fetchone()
        return dict(attempt=attempt,fault=record('e2e_fault','green-worker-interruption'),
            notification=record('e2e_probe','notification_failure'),sent_at=sent[0] if sent else None)
    finally: db.close()

def receipts(attempt):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(8); client.connect(SOCKET)
        client.sendall(json.dumps(dict(operation='recovery_receipts',attempt=attempt)).encode()+b'\n')
        with client.makefile('rb') as stream: result=json.loads(stream.readline(65536))
    if result.get('error') or result.get('attempt')!=attempt:
        raise RuntimeError('coordination receipt service unavailable or wrong attempt: '+str(result))
    return result

class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(5)
        try: result=read_receipts(self.server.path,self.server.attempt,json.loads(self.rfile.readline(4096)))
        except Exception as exc: result=dict(error=type(exc).__name__)
        self.wfile.write(json.dumps(result).encode()+b'\n')

if __name__=='__main__':
    path=Path(SOCKET); path.parent.mkdir(parents=True,exist_ok=True)
    path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(SOCKET,Handler) as server:
        server.path='/coordination/coordination.db'
        server.attempt=os.environ['HERMES_EXECUTION_ATTEMPT']
        os.chmod(path,0o666)
        print('Fixed coordination receipt reader ready',flush=True)
        server.serve_forever()
