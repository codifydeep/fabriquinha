"""Fixed, synthetic installed-handler probe. No product delivery is modified."""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def classify(before,after,final,receipt):
    if receipt.get('operation')!='patch_handler_receipt_v1':raise ValueError('typed handler receipt required')
    if receipt.get('delivery_approval') is not False or receipt.get('author_retry_authorized') is not False:
        raise ValueError('non-authorizing receipt required')
    if receipt.get('no_change') is True and before==after==final:return 'observed_noop'
    if (receipt.get('success') is True and receipt.get('changed') is False
            and receipt.get('diff_bytes')==0 and before==after==final):return 'observed_unchanged_success'
    if receipt.get('changed') is True and before!=after:
        return 'observed_persistent_change' if after==final else 'observed_later_change'
    return 'inconclusive'


def run():
    if os.environ.get('HERMES_WRITE_SAFE_ROOT')!='/tmp':
        raise ValueError('probe requires isolated tmpfs write root /tmp')
    sys.path.insert(0,'/opt/hermes')
    from tools.file_tools import _handle_patch
    from patch_receipt_contract import receipt
    source=Path('/opt/hermes/acp_adapter/tools.py').read_text()
    node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='_format_edit_result')
    node.returns=None
    for arg in node.args.args:arg.annotation=None
    namespace={'json':json,'_json_loads_maybe':json.loads}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'<installed-formatter>','exec'),namespace)
    formatter=namespace['_format_edit_result']
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    cases=[]
    with tempfile.TemporaryDirectory(prefix='synthetic-patch-') as folder:
        path=Path(folder)/'sample.py'
        path.write_text('value = 1\n')
        def patch(old,new):
            raw=_handle_patch(dict(mode='replace',path=str(path),old_string=old,new_string=new),task_id='synthetic-persistence-probe')
            facts=receipt('patch',raw)
            if not facts or json.loads(formatter('patch',raw,{'path':str(path)}))!=facts:
                raise ValueError('actual handler and installed formatter diverge')
            if not facts['success']:
                error=str(json.loads(raw).get('error',''))
                raise ValueError(json.dumps(dict(handler_failed=True,receipt=facts,
                    synthetic_error=error.replace(str(path),'<synthetic-file>')[:180],
                    error_sha256=hashlib.sha256(error.encode()).hexdigest(),
                    categories=[s for s in ('write denied','permission','read-only','verification','failed to read',
                        'failed to write','not found','terminal','policy','fence','no changes','old_string')
                        if s in error.lower()]),sort_keys=True))
            return facts
        def reopened():
            code='import hashlib,sys;from pathlib import Path;print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())'
            return subprocess.check_output([sys.executable,'-c',code,str(path)],text=True).strip()
        before=sha(path);facts=patch('value = 1','value = 2');after=sha(path);final=reopened()
        cases.append(dict(kind=classify(before,after,final,facts),before=before,after=after,final=final,handler=facts))
        before=sha(path);facts=patch('value = 1','value = 2');after=sha(path);final=reopened()
        cases.append(dict(kind=classify(before,after,final,facts),before=before,after=after,final=final,handler=facts))
        before=sha(path);facts=patch('value = 2','value = 3');after=sha(path)
        reverted=patch('value = 3','value = 2');final=reopened()
        if reverted['changed'] is not True:raise ValueError('actual reverse control failed')
        cases.append(dict(kind=classify(before,after,final,facts),before=before,after=after,final=final,handler=facts))
    if (cases[0]['kind']!='observed_persistent_change'
            or cases[1]['kind'] not in ('observed_noop','observed_unchanged_success')
            or cases[2]['kind']!='observed_later_change'):
        raise ValueError(json.dumps({'synthetic_controls_failed':cases},sort_keys=True))
    return dict(operation='installed_patch_persistence_probe_v1',cases=cases,
        formatter_sha256=hashlib.sha256(source.encode()).hexdigest(),
        handler_sha256=hashlib.sha256(Path('/opt/hermes/tools/file_tools.py').read_bytes()).hexdigest(),
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        synthetic_only=True,historical_cause='unknown',product_files_modified=False,
        author_retry_authorized=False,delivery_approval=False)


if __name__=='__main__':print(json.dumps(run(),sort_keys=True))
