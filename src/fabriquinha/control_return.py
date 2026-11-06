"""Evidence for returning an unnecessary fixture repair to the mutation author."""

from .quality import Quality
from .recovery import suite_refusal_context


def return_candidate(project, store, parent, incident_key):
    """Identify the prior reviewed freeze. This read grants no dispatch authority."""
    from .repairs import reviewed

    admission = store.receipt(parent, kind='test_repair_admission')
    repair = reviewed(project, store, parent)['context']
    current = store.receipt(incident_key, kind='incident')
    source = store.receipt(repair['incident'], kind='incident')
    qa, backend = current['binding'], source['binding']
    facts = current['payload']
    freeze = store.receipt(repair['tests'], kind='tests_frozen')
    frozen = freeze['payload']
    if (qa['kind'] != 'tests' or qa['reviewing'] or qa['actor'] != qa['author']
            or qa['author'] != frozen['test_author'] or qa['release'] != backend['release']
            or facts['project'] != project.fingerprint() or facts['source_state'] != 'triage'
            or facts['source'] != qa['task'] or facts['source_run'] != qa['number']
            or facts['controller_effects'] or facts['snapshot'] != frozen['snapshot']
            or admission['binding']['release'] != qa['release']
            or backend['kind'] != 'implementation' or backend['reviewing']
            or backend['actor'] != backend['author']):
        raise ValueError('unchanged triaged fixture and exact implementation author required')
    job = source['payload'].get('suite_refusal')
    if not job:
        raise ValueError('sealed negative-control refusal required')
    result = suite_refusal_context(store, project, backend, job, repair['implementation_snapshot'])
    if result.get('control_issue') != 'invalid_mutation' or result['freeze'] != repair['tests']:
        raise ValueError('invalid mutation on the exact independently frozen tests required')
    green = store.receipt(result['green'], kind='green')['payload']
    if green['snapshot'] != repair['implementation_snapshot']:
        raise ValueError('original Green implementation changed')
    Quality(project, store, None, None).protect(frozen['snapshot'], green['snapshot'], exact_tests=True)
    return dict(parent=parent, incident=incident_key, invalid_job=job, green=result['green'],
                tests=repair['tests'], snapshot=green['snapshot'], owner=backend['author'],
                prior_graph=repair['prior_graph'], implementation=backend['task'],
                implementation_run=backend['number'], delivery_approval=False)


def admission_context(project, store, parent, decision_key, graph_key):
    decision = store.receipt(decision_key, kind='diagnostic_decision')
    choice, actor = decision['payload'], decision['binding']
    incident = store.receipt(choice['incident'], kind='incident')
    graph = store.receipt(graph_key, kind='release_graph')
    if (choice['action'] != 'return_controls' or not choice.get('experiment')
            or choice.get('delivery_approval') is not False or choice['project'] != project.fingerprint()
            or actor['kind'] != 'diagnostic' or actor['reviewing']
            or actor['actor'] != project.technical_roles['cto'] or actor['author'] != actor['actor']
            or actor['release'] != incident['binding']['release']
            or graph['binding'] != store.receipt(parent)['binding']
            or graph['payload'].get('continuation_review') != parent):
        raise ValueError('fresh CTO control-return decision on current fixture graph required')
    experiment = store.receipt(choice['experiment'], kind='diagnostic_experiment')
    if (experiment['binding'] != actor or experiment['payload']['incident'] != choice['incident']
            or experiment['payload']['project'] != project.fingerprint()
            or experiment['payload']['snapshot'] != incident['payload']['snapshot']):
        raise ValueError('current scoped CTO experiment required')
    proof = return_candidate(project, store, parent, choice['incident'])
    source = incident['binding']
    cards = [item['cards']['tests'] for item in graph['payload']['items']]
    if not any(card['id'] == source['task'] and card['body']['inputs'].get('repair_review') == parent
               for card in cards):
        raise ValueError('fixture author no longer owns the active graph card')
    return dict(project=project.fingerprint(), proof=proof, current_diagnosis=decision_key,
                prior_graph=graph_key, repair_kind='control_return', source=source['task'],
                source_run=source['number'], snapshot=incident['payload']['snapshot'],
                submission_contract='Use the previously reviewed freeze. Author fresh Green and a complete mapped '
                'batch, starting with the disputed mutations. Each must fail by an assertion; transport errors '
                'require changing the mutant. Independent implementation review is mandatory.')
