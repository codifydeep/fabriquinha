"""Operator-owned, question-bound product answers. No dispatch or permission grants."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

FLAGS=('authorizes_merge','authorizes_tools','waives_security','approves_brief')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def binding(ledger):
    if not isinstance(ledger,dict):raise ValueError('pending planning ledger required')
    questions=ledger.get('questions')
    output=(ledger.get('outputs') or {}).get('product') or {}
    if (ledger.get('stage')!='blocked_awaiting_ceo' or ledger.get('owner')!='ceo'
            or set(ledger.get('outputs') or {})!={'product'}
            or not isinstance(questions,list) or not questions
            or any(not isinstance(q,str) or not q.strip() for q in questions)
            or output.get('proposal',{}).get('business_questions')!=questions):
        raise ValueError('answer requires the exact pending Product question')
    return {key:ledger[key] for key in ('name','brief_sha256','configuration_sha256','base_sha')} | {
        'question_sha256':digest(questions),'issue_id':ledger['issues']['product'],
        'task_id':output['task_id']}


def make_answer(ledger,answer,source):
    if (not isinstance(answer,str) or not 1<=len(answer.strip())<=512
            or not isinstance(source,str) or not 1<=len(source.strip())<=128):
        raise ValueError('bounded direct human answer and provenance required')
    return {'schema':'planning-ceo-answer-v1','scope':'product_behavior',**binding(ledger),
            'answer':answer.strip(),'source':source.strip(),**{key:False for key in FLAGS}}


def resume(ledger,receipt):
    if 'ceo_answer' in ledger:
        if ledger['ceo_answer']!=receipt:
            raise ValueError('consumed CEO answer identity drift')
        return None
    expected=make_answer(ledger,receipt.get('answer'),receipt.get('source'))
    if receipt!=expected:
        raise ValueError('CEO answer identity or authority drift')
    result=copy.deepcopy(ledger)
    result['prior_ceo_question']={'output':result['outputs']['product'],
        'issue_id':result['issues']['product'],'questions':result['questions']}
    result.update(ceo_answer=copy.deepcopy(receipt),outputs={},stage='resuming_product_after_ceo')
    for key in ('owner','questions','active','category','next_action'):
        result.pop(key,None)
    return result


def receipt_at(private,name):
    if not re.fullmatch(r'[A-Z][A-Z0-9-]{2,40}',name):
        raise ValueError('invalid planning run identity')
    if Path(private).is_symlink():raise ValueError('unsafe private directory')
    path=Path(private).resolve()/'planning-ceo-answers'/(name+'.json')
    if any(p.is_symlink() for p in (path,*path.parents)):
        raise ValueError('unsafe CEO answer path')
    if not path.exists():return None
    if not path.is_file() or path.stat().st_size>4096 or path.stat().st_mode & 0o077:
        raise ValueError('CEO answer must be bounded and private')
    return json.loads(path.read_text())


def pending(private,name,ledger):
    receipt=receipt_at(private,name)
    return receipt is not None and resume(ledger,receipt) is not None


def context(body,ledger):
    receipt=ledger.get('ceo_answer')
    if not receipt:return body
    if receipt.get('scope')!='product_behavior' or any(receipt.get(key) is not False for key in FLAGS):
        raise ValueError('product answer cannot expand authority')
    return body+'\nCEO product clarification (binding to this brief only): '+receipt['answer']


def main():
    from evalctl import PRIVATE
    from release_eval import save_receipt
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',required=True)
    parser.add_argument('--answer',required=True)
    parser.add_argument('--source',required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Z][A-Z0-9-]{2,40}',args.run):raise ValueError('invalid run')
    path=PRIVATE/'planning-intake'/(args.run+'.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:
        raise ValueError('pending ledger missing or unsafe')
    ledger=json.loads(path.read_text())
    receipt=make_answer(ledger,args.answer,args.source)
    existing=receipt_at(PRIVATE,args.run)
    if existing is not None and existing!=receipt:raise ValueError('immutable CEO answer drift')
    if existing is None:save_receipt(PRIVATE/'planning-ceo-answers'/(args.run+'.json'),receipt)
    print(json.dumps({'run':args.run,'stage':'ceo_answer_registered',
                     'question_sha256':receipt['question_sha256'],'scope':receipt['scope'],
                     'dispatch_started':False}))


if __name__=='__main__':main()
