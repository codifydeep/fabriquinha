"""Task-specific worker selection with the ORIGINAL reviewed Red provenance.

No Red is reconstructed and no issue-wide permission is enlarged. The fixed
seed job verifies the historical snapshot bytes and the lockdown job enforces
the revised contract; ACP receives the very same bounded code-only paths.
"""
import json
import re
from portable_contract import validate, is_test_path
try:
    from . import product_scope_task_binding as binding
except ImportError:
    import product_scope_task_binding as binding


def selection(b,issue_id,task_id):
    selected=binding.lookup(b,issue_id,task_id)
    if selected is None:return None
    contract=validate(selected['contract'])
    with b.db() as con:
        red_row=con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(issue_id,)).fetchone()
        review_row=con.execute('SELECT state FROM test_revision_trials WHERE issue_id=?',(issue_id,)).fetchone()
        route_row=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue_id,)).fetchone()
    if not red_row or not review_row or not route_row:raise ValueError('existing independently reviewed Red required')
    red=json.loads(red_row[0]);review=json.loads(review_row[0]);route=json.loads(route_row[0])
    facts=red['red'];decision=review.get('decision') or {}
    if (red.get('issue_id')!=issue_id or not red.get('task_id') or red['task_id']==task_id
            or route.get('enabled') is not True or route.get('test_first') is not True
            or route.get('author')!=selected['author']
            or set(route['test_first_files'])!=set(selected['frozen_test_sha256'])
            or facts.get('base_manifest_sha256')!=selected['original_base_manifest_sha256']
            or facts.get('test_sha256')!=selected['frozen_test_sha256']
            or facts.get('command')!=contract['test_command']
            or type(facts.get('exit_code')) is not int or facts['exit_code']==0
            or type(facts.get('test_count')) is not int or facts['test_count']<=0
            or any(not isinstance(facts.get(k),str) or not re.fullmatch(r'[a-f0-9]{64}',facts[k])
                   for k in ('manifest_sha256','output_sha256'))
            or review.get('status')!='approved' or review.get('source_task')!=red['task_id']
            or review.get('candidate_volume')!=red['volume']
            or review.get('manifest_sha256')!=facts['manifest_sha256']
            or not review.get('review_task') or review['review_task'] in (task_id,red['task_id'])
            or review.get('read_contract')!='complete-lines-v2'
            or decision.get('action')!='approve_test_revision'
            or decision.get('manifest_sha256')!=facts['manifest_sha256'] or decision.get('optional_files')!=[]):
        raise ValueError('scope revision cannot replace historical Red or its independent approval')
    volume=b.docker('GET','/volumes/'+red['volume'])
    if (not volume or volume.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
            or volume.get('Labels',{}).get('delivery-kit.test-first-task')!=red['task_id']):
        raise ValueError('historical Red volume ownership changed')
    paths=[name for name in contract['editable_files'] if name not in contract['test_files']
           and not any(is_test_path(name,root,contract['test_command'][0]) for root in contract['test_roots'])]
    if not paths:raise ValueError('scope worker requires bounded code-only paths')
    return dict(base=dict(volume=selected['volume'],base_sha=selected['base_sha'],manifest_sha256=selected['manifest_sha256']),
        editable_paths=['/workspace/'+name for name in sorted(paths)],
        seed=dict(mount=dict(Type='volume',Source=red['volume'],Target='/previous',ReadOnly=True),
                  selection={k:facts[k] for k in ('manifest_sha256','test_sha256')}),
        provenance=dict(red_task=red['task_id'],review_task=review['review_task'],
                        red_manifest_sha256=facts['manifest_sha256'],historical_red_recreated=False))
