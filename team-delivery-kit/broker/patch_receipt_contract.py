"""ACP-visible patch facts, never delivery evidence or tool authorization.

Hermes' human formatter drops no_change and diff. Preserve bounded metadata
from the original handler result, without persisting source or error text.
Final filesystem/snapshot hashes still decide whether a delivery changed.
"""
import ast
import hashlib
import json


def receipt(tool, raw):
    if tool!='patch' or not isinstance(raw,str) or len(raw)>4*1024*1024:return None
    try:value=json.loads(raw)
    except (ValueError,TypeError):return None
    if not isinstance(value,dict):return None
    diff=value.get('diff')
    known_diff=isinstance(diff,str) and 0<len(diff.encode())<=2*1024*1024
    success=value.get('success') is True and not value.get('error')
    noop=value.get('no_change') is True or value.get('already_applied') is True
    changed=bool(success and not noop and known_diff)
    return dict(operation='patch_handler_receipt_v1',success=bool(success),
                no_change=noop,changed=changed,
                diff_sha256=hashlib.sha256(diff.encode()).hexdigest() if known_diff else None,
                diff_bytes=len(diff.encode()) if known_diff else 0,
                evidence_scope='original_handler_result_not_final_snapshot',
                delivery_approval=False,author_retry_authorized=False)


ANCHOR='    data = _json_loads_maybe(result)\n    path = str((args or {}).get("path") or "file").strip()\n'
REPLACEMENT='''    try:
        from patch_receipt_contract import receipt as patch_receipt
    except ImportError:
        from broker.patch_receipt_contract import receipt as patch_receipt
    patch_facts=patch_receipt(tool_name,result)
    if patch_facts is not None:
        return json.dumps(patch_facts,sort_keys=True)
'''+ANCHOR


def adapt(source):
    ast.parse(source)
    if source.count(ANCHOR)!=1 or 'patch_facts=patch_receipt' in source:
        raise ValueError('pinned ACP patch formatter changed')
    result=source.replace(ANCHOR,REPLACEMENT)
    compile(result,'<patch-receipt-formatter>','exec')
    return result


if __name__=='__main__':
    from pathlib import Path
    path=Path('/opt/hermes/acp_adapter/tools.py')
    if path.is_symlink():raise ValueError('unexpected ACP source symlink')
    path.write_text(adapt(path.read_text()))
