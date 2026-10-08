"""Sanitized controller fault location; never exports exception text or locals."""
import hashlib
from pathlib import Path
import traceback


def describe(error):
    frames=traceback.extract_tb(error.__traceback__)
    frame=frames[-1] if frames else None
    return dict(event='watchdog_reconciliation_failed',
        error_type=type(error).__name__,error_sha256=hashlib.sha256(str(error).encode()).hexdigest(),
        module=Path(frame.filename).name if frame else None,
        function=frame.name if frame else None,line=frame.lineno if frame else None,
        delivery_approval=False)
