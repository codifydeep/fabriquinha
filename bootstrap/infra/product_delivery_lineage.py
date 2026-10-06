"""Resolve integrated evidence through explicit preserved delivery ancestry."""
def lineage(cards,task):
    result=[];seen=set()
    while task:
        if task in seen:raise PermissionError('cyclic delivery ancestry: '+task)
        if task not in cards:raise PermissionError('unregistered delivery ancestor: '+task)
        seen.add(task);result.append(task);card=cards[task]
        original=card.get('original_source_task');base=card.get('base_update_source',{}).get('task')
        if original and base and original!=base:raise PermissionError('ambiguous delivery ancestry: '+task)
        task=original or base
    return result

def integrated_index(cards,publications):
    result={}
    for pub in publications:
        if pub.get('state')!='INTEGRATED':continue
        if not pub.get('merge') or not pub.get('head'):raise PermissionError('integration proof missing exact commit')
        chain=lineage(cards,pub['source_task'])
        for task in chain:
            card=cards[task]
            if card.get('rework_pr') and card['rework_pr']!=pub['pr']:raise PermissionError('delivery PR ancestry mismatch')
            if task in result and result[task]['merge']!=pub['merge']:raise PermissionError('multiple integrations for one delivery require reconciliation')
            result[task]=dict(pub,delivery_lineage=chain)
    return result
