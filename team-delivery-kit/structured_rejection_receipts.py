"""Durable sanitized validator failures; no rejected content or approval."""
import json
import re
import uuid
from deterministic_read_dispatch import ledger


def from_event(event):
    if (event.get('event')!='model_proxy_request' or event.get('status')!=502
            or event.get('category')!='structured_decision_response_invalid'):return None
    category=event.get('structured_rejection_category')
    allowed={'schema_violation','calibration_response_invalid','nonterminal_or_non_json_response'}
    if category not in allowed:return None # Typed decision failures have their separate durable ledger.
    execution=event.get('execution_id');call=event.get('call_number')
    if execution is None:return None # An unbound legacy/synthetic response cannot be task evidence.
    if not isinstance(execution,str) or str(uuid.UUID(execution))!=execution or type(call) is not int or call<1:
        raise ValueError('exact structured rejection identity required')
    diagnostic=event.get('structured_rejection_diagnostic')
    if diagnostic is not None:
        version=diagnostic.get('version')
        expected=({'version','constraints','upstream_sha256'} if version=='structured-constraint-v1' else
            {'version','category','constraints','fields','missing_fields','upstream_sha256'} if version=='calibration-constraint-v1' else set())
        keywords={'type','enum','required','additionalProperties','minLength','maxLength','minItems',
            'maxItems','minProperties','maxProperties','pattern','minimum','maximum','anyOf',
            'oneOf','allOf','not','uniqueItems','other'}
        fields={'action','engine','modules','negatives','previous_methods','controls','execution_authorized',
            'delivery_approval','reason','path','fixture_attribute','product_path','positive_fixture','classes',
            'id','module','class_name','method','fixture','criteria','fixtures','attribute','replacements'}
        if not expected or set(diagnostic)!=expected or not re.fullmatch('[a-f0-9]{64}',str(diagnostic['upstream_sha256'])):
            raise ValueError('bounded sanitized rejection required')
        for key,vocabulary in (('constraints',keywords),('fields',fields),('missing_fields',fields)):
            if key not in diagnostic:continue
            items=diagnostic[key]
            if not isinstance(items,list) or any(not isinstance(v,str) for v in items) or items!=sorted(set(items)) or not set(items)<=vocabulary:
                raise ValueError('untrusted rejection values forbidden')
        if version=='calibration-constraint-v1' and diagnostic['category'] not in ('schema_violation','invalid_json','invalid_transport_or_tool'):
            raise ValueError('fixed calibration rejection category required')
    return dict(operation='structured_validator_rejection_v1',execution_id=execution,call_number=call,
        category=category,diagnostic=diagnostic,response_forwarded=False,worker_tool_executed=False,
        execution_authorized=False,delivery_approval=False)


def record(counter,event):
    receipt=from_event(event)
    if receipt is None:return
    with ledger(counter) as con:
        con.execute('CREATE TABLE IF NOT EXISTS structured_rejections(execution_id TEXT,call_number INTEGER,receipt TEXT,PRIMARY KEY(execution_id,call_number))')
        key=(receipt['execution_id'],receipt['call_number']);encoded=json.dumps(receipt,sort_keys=True)
        old=con.execute('SELECT receipt FROM structured_rejections WHERE execution_id=? AND call_number=?',key).fetchone()
        if old and old[0]!=encoded:raise ValueError('structured rejection drift')
        if not old:con.execute('INSERT INTO structured_rejections VALUES(?,?,?)',(*key,encoded))


def read(counter,execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical execution required')
    with ledger(counter) as con:
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='structured_rejections'").fetchone():return []
        return [json.loads(row[0]) for row in con.execute('SELECT receipt FROM structured_rejections WHERE execution_id=? ORDER BY call_number',(execution,))]
