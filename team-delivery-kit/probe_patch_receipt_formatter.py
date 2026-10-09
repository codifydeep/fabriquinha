"""Offline qualification of the installed ACP formatter; no tool execution."""
import ast
import hashlib
import json
from pathlib import Path
import sys


def run():
    sys.path.insert(0,'/opt/hermes')
    source=Path('/opt/hermes/acp_adapter/tools.py').read_text()
    if source.count('patch_facts=patch_receipt')!=1:
        raise ValueError('exact installed receipt adapter required')
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)
              and n.name=='_format_edit_result')
    node.returns=None
    for arg in node.args.args:arg.annotation=None
    namespace={'json':json,'_json_loads_maybe':json.loads}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<installed-formatter>','exec'),namespace)
    formatter=namespace['_format_edit_result']
    noop=json.loads(formatter('patch',json.dumps({'success':True,'no_change':True}),{}))
    changed=json.loads(formatter('patch',json.dumps({'success':True,'diff':'private diff'}),{}))
    failed=json.loads(formatter('patch',json.dumps({'success':False,'error':'private error'}),{}))
    if (noop['changed'] is not False or noop['no_change'] is not True
            or changed['changed'] is not True or failed['changed'] is not False
            or any(r['delivery_approval'] is not False or r['author_retry_authorized'] is not False
                   for r in (noop,changed,failed))
            or changed['diff_sha256']!=hashlib.sha256(b'private diff').hexdigest()
            or any(text in json.dumps((noop,changed,failed)) for text in ('private diff','private error'))):
        raise ValueError('installed formatter receipt qualification failed')
    return dict(operation='installed_patch_receipt_qualification_v1',
                formatter_sha256=hashlib.sha256(source.encode()).hexdigest(),
                noop_preserved=True,diff_hash_preserved=True,source_exposed=False,
                tools_executed=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
