"""Resolve two approvals only through a qualified controller revalidation lineage."""
import json

PROGRAM='''import broker as b,json,sys,product_scope_delivery as p
issue=sys.argv[1];source=sys.argv[2]
with b.db() as c:
 row=c.execute('SELECT stage,data FROM delivery_handoffs WHERE issue_id=? AND source_task=?',(issue,source)).fetchone()
 route=c.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()
 snapshot=c.execute('SELECT volume FROM snapshots WHERE task_id=?',(source,)).fetchone()
 if not row or row[0]!='approved' or not route or not snapshot:print('null');sys.exit()
 data=json.loads(row[1]);route=json.loads(route[0]);review=data.get('review') or {};previous=data.get('previous_review') or {};inspection=data.get('inspection_revalidation') or {}
 if route.get('enabled') is not True or data.get('policy_revalidation') is not True:print('null');sys.exit()
 delivery=dict(source_task=source,review_task=review['review_task_id'],author=route['author'],reviewer=review['reviewer_agent_id'],manifest_sha256=review['manifest_sha256'],volume=snapshot[0])
proof=p.qualified(b,issue,delivery)
if proof is None:print('null');sys.exit()
print(json.dumps(dict(delivery=delivery,previous_review=previous,inspection=inspection,qualification=dict(operation=proof['operation'],issue_id=proof['issue_id'],delivery=proof['delivery'],release_homologated=proof['release_homologated']))))
'''


def select(issue, rows, query):
    if len(rows)!=2 or any(not isinstance(row,(list,tuple)) or len(row)!=8 for row in rows):
        raise ValueError('expected one approved exact revision')
    if rows[0][1:]!=rows[1][1:] or rows[0][0]==rows[1][0]:
        raise ValueError('ambiguous approved deliveries cannot be resolved')
    source,reviewer,manifest,status,volume,frozen,author=rows[0][1:]
    if status!='approved' or frozen!='complete' or author==reviewer:
        raise ValueError('independent immutable approvals required')
    report=query(issue,source)
    if not isinstance(report,dict) or set(report)!={'delivery','previous_review','inspection','qualification'}:
        raise ValueError('qualified scoped approval lineage required')
    delivery=report['delivery'];previous=report['previous_review'];inspection=report['inspection'];q=report['qualification']
    if any(not isinstance(value,dict) for value in (delivery,previous,inspection,q)):
        raise ValueError('structured scoped revalidation required')
    common=dict(source_task_id=source,reviewer_agent_id=reviewer,manifest_sha256=manifest,status='approved')
    expected=dict(source_task=source,author=author,reviewer=reviewer,manifest_sha256=manifest,volume=volume)
    if (not isinstance(delivery,dict) or set(delivery)!=set(expected)|{'review_task'}
            or any(delivery.get(k)!=v for k,v in expected.items())
            or previous!={**common,'review_task_id':inspection.get('review_task')}
            or inspection.get('operation')!='qualified_scoped_review_inspection_v1'
            or inspection.get('source_task')!=source or inspection.get('manifest_sha256')!=manifest
            or inspection.get('author_restarted') is not False or inspection.get('delivery_approval') is not False
            or not isinstance(inspection.get('read_paths'),list) or not inspection['read_paths']
            or not isinstance(inspection.get('missing_read_paths'),list) or not inspection['missing_read_paths']
            or not set(inspection['missing_read_paths'])<=set(inspection['read_paths'])
            or {delivery.get('review_task'),previous.get('review_task_id')}!={row[0] for row in rows}
            or q!=dict(operation='qualified_product_scope_delivery_v1',issue_id=issue,
                       delivery=delivery,release_homologated=False)):
        raise ValueError('exact qualified scoped revalidation required')
    return [row for row in rows if row[0]==delivery['review_task']][0]


def query_with(command,broker,issue,source):
    return json.loads(command('docker','exec','-w','/',broker,'python','-c',PROGRAM,issue,source))
