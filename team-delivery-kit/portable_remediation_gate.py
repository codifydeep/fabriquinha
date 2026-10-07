"""Fixed read-only qualification bridge from the portable driver to the broker."""
import json
import re

QUERY = (
    'import broker as b,json,sys; '
    'con=b.db(); '
    'exists=con.execute("SELECT 1 FROM sqlite_master WHERE name=\'remediation_red_references\'").fetchone(); '
    'row=con.execute("SELECT 1 FROM remediation_red_references WHERE issue_id=?",(sys.argv[1],)).fetchone() if exists else None; '
    'con.close(); '
    'proof=None; '
    '\nif row:\n'
    ' import remediation_delivery\n'
    ' proof=remediation_delivery.qualified(b,sys.argv[1],json.loads(sys.argv[2]))\n'
    'print(json.dumps(proof))'
)


def qualify(command,instance,context,delivery,*,previous=None):
    """An absent legacy reference is not permission to erase a recovery proof."""
    proof=json.loads(command('docker','exec',instance+'-execution-broker-1','python','-c',
                             QUERY,context['issue_id'],json.dumps(delivery,sort_keys=True)))
    if proof is None:
        if previous is not None:raise ValueError('registered recovery delivery proof disappeared')
        return None
    fields={'operation','issue_id','source_task','run_id','execution_contract_sha256','r1_gate_sha256',
            'reference_sha256','delivery','tdd_sha256','red_origin_issue','red_origin_task',
            'original_depth','release_homologated'}
    if (not isinstance(proof,dict) or set(proof)!=fields
            or proof['operation']!='qualified_remediation_r2_delivery_v1'
            or proof['issue_id']!=context['issue_id'] or proof['delivery']!=delivery
            or proof['red_origin_issue']==context['issue_id']
            or proof['red_origin_task']==delivery['source_task']
            or any(not isinstance(proof[k],str) or not proof[k] for k in
                   ('source_task','run_id','red_origin_issue','red_origin_task'))
            or any(not isinstance(proof[k],str) or not re.fullmatch('[0-9a-f]{64}',proof[k])
                   for k in ('execution_contract_sha256','r1_gate_sha256','reference_sha256','tdd_sha256'))
            or type(proof['original_depth']) is not int or proof['original_depth'] not in (1,2)
            or proof['release_homologated'] is not False
            or previous is not None and proof!=previous):
        raise ValueError('exact unchanged nonterminal recovery delivery proof required')
    return proof
