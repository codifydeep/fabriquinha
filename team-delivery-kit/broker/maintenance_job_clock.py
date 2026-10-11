"""Exclude proved sealed operator downtime from fixed-job observation budgets.

Original deadlines remain immutable. Draining, provider pauses and ordinary
inactivity do not extend a deadline; a currently sealed controller runs no job.
"""
import json
import math


def deadline(con,namespace,original,now,budget=600):
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='controller_maintenance'").fetchone():
        return original
    intervals=[];since=original-budget
    for row in con.execute('SELECT stage,receipt FROM controller_maintenance'):
        stage,raw=row;receipt=json.loads(raw)
        if receipt.get('namespace')!=namespace:continue
        if stage=='sealed':raise TimeoutError('operator maintenance sealed; fixed job remains under observation')
        if stage!='released':continue
        start=receipt.get('sealed_at');end=receipt.get('released_at')
        if start is None:continue
        if any(type(t) not in (int,float) or not math.isfinite(t) for t in (start,end)) or end<start:
            raise ValueError('invalid proved maintenance interval')
        start=max(start,since);end=min(end,now)
        if end>start:intervals.append((start,end))
    # Union prevents overlapping/corrupted records from granting double time.
    elapsed=0;last=None
    for start,end in sorted(intervals):
        if last is None or start>last:elapsed+=end-start
        elif end>last:elapsed+=end-last
        last=max(last or end,end)
    return original+elapsed
