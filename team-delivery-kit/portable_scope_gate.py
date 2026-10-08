"""Fixed read-only effective-contract bridge; no inferred scope permissions."""
import json
import re
from broker.product_scope_revision import digest
from portable_contract import validate

QUERY=('import sys;sys.path.insert(0,"/");import broker as b,json,product_scope_delivery;'
       'print(json.dumps(product_scope_delivery.qualified(b,sys.argv[1],json.loads(sys.argv[2]))))')


def qualify(command,instance,context,delivery,original,*,previous=None):
    proof=json.loads(command('docker','exec',instance+'-execution-broker-1','python','-c',QUERY,
                             context['issue_id'],json.dumps(delivery,sort_keys=True)))
    if proof is None:
        if previous is not None:raise ValueError('previous scope proof cannot disappear')
        return None
    keys={'operation','issue_id','delivery','plan_key','base_sha','original_contract_sha256',
          'effective_contract_sha256','contract','scope_tdd_sha256','release_homologated'}
    if (not isinstance(proof,dict) or set(proof)!=keys or proof['operation']!='qualified_product_scope_delivery_v1'
            or proof['issue_id']!=context['issue_id'] or proof['delivery']!=delivery
            or proof['base_sha']!=context['base_sha'] or proof['original_contract_sha256']!=digest(original)
            or context['contract_sha256']!=digest(original) or proof['release_homologated'] is not False
            or any(not isinstance(proof[k],str) or not re.fullmatch(r'[a-f0-9]{64}',proof[k])
                   for k in ('plan_key','scope_tdd_sha256'))
            or proof['effective_contract_sha256']!=digest(validate(proof['contract']))
            or previous is not None and proof!=previous):
        raise ValueError('exact unchanged independently reviewed effective scope contract required')
    revised=proof['contract']
    if any(revised[k]!=original[k] for k in original.keys()-{'editable_files','protected_files'}):
        raise ValueError('scope revision cannot change acceptance, tests, CI or deployment contract')
    added=set(revised['editable_files'])-set(original['editable_files'])
    if (not added or not added<=set(original['protected_files'])-set(original['test_files'])
            or set(original['editable_files'])-set(revised['editable_files'])
            or set(revised['protected_files'])!=set(original['protected_files'])-added):
        raise ValueError('only reviewed protected product code may expand scope')
    return proof
