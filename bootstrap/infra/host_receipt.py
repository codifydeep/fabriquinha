"""Bounded wait for the fixed local host verifier, with durable rejection evidence."""
import json
from pathlib import Path
import time

class HostReceiptPending(RuntimeError):
    def __init__(self,detail):
        self.detail=detail
        super().__init__(json.dumps(detail))

def wait_receipt(path,commit,url,record,timeout=45):
    deadline=time.monotonic()+timeout
    while True:
        host={}; reason=None
        try:
            host=json.loads(Path(path).read_text())
            age=time.time()-host.get('at',0)
            if host.get('origin')!='macOS-host': reason='wrong_origin'
            elif host.get('url')!=url: reason='wrong_url'
            elif host.get('commit')!=commit: reason='wrong_commit'
            elif not host.get('passed') or host.get('checks')!=10: reason='checks_not_passed'
            elif not 0<=age<60: reason='stale_or_future_receipt'
        except (OSError,ValueError,TypeError,AttributeError) as exc:
            reason=type(exc).__name__
        detail=dict(category='host_receipt_pending',expected_commit=commit,expected_url=url,
            observed=host,reason=reason,at=time.time(),ceo_required=False,
            next_action='Wait for local macOS verifier; no credentials or external host required.',block_required=True)
        record(detail)
        if reason is None: return host
        if time.monotonic()>=deadline: raise HostReceiptPending(detail)
        time.sleep(min(2,max(0,deadline-time.monotonic())))
