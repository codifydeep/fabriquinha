"""Keep failed candidate evidence; never merge it to obtain a recovery base."""
import json

from portable_qa_incident import failing_case


def correction_payload(context, receipt, incident, contract, diagnosis):
    proposal = json.loads(diagnosis)
    allowed = set(contract['editable_files']) - set(contract['test_files'])
    paths = proposal.get('editable_code_files')
    if (proposal.get('decision') != 'repair'
            or not isinstance(paths, list) or not paths or not set(paths) <= allowed
            or not isinstance(proposal.get('root_cause'), str)):
        raise ValueError('candidate diagnosis must request bounded code-only correction')
    if (incident['phase'] != 'candidate' or receipt.get('merge_sha') or receipt.get('pr_url')
            or receipt['head_sha'] != incident['source_sha']):
        raise ValueError('candidate correction requires exact unmerged pre-PR receipt')
    case = failing_case(contract, incident['category'])
    finding = ('Pre-PR controller QA FAILED on candidate ' + incident['source_sha']
               + '. Exact unchanged acceptance case: ' + json.dumps(case, sort_keys=True)
               + '. Inspect actual source; diagnosis is a hypothesis, not verified code evidence. '
                 'Correct product behavior, not marker comments. Preserve EVERY existing test '
                 'including the frozen newly authored test and the historical Red receipt. '
                 'Edit only these original code paths: ' + ', '.join(sorted(set(paths)))
               + '. Run the full pinned unit suite. The controller will independently rerun '
                 'this SAME failing HTTP assertion before PR creation. Do not recreate Red, '
                 'change QA acceptance, weaken tests, or ask the CEO about this technical repair.')
    return {'issue_id': context['issue_id'], 'source_task': receipt['delivery']['source_task'],
            'manifest_sha256': receipt['delivery']['manifest_sha256'],
            'incident_key': incident['key'], 'finding': finding}


def verify_preserved_tests(before, after, contract):
    if set(before) != set(after):
        raise ValueError('candidate correction changed declared delivery topology')
    frozen = set(contract['test_files']) | set(contract['protected_files'])
    if any(before[name] != after[name] for name in frozen):
        raise ValueError('candidate correction changed frozen tests or protected files')
