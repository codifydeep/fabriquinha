"""Native finding adapter using the existing typed citation wire contract.

Expected/observed carry closed fact tokens, not inferred review prose. This
qualifies a CTO's NEW factual disagreement, never rewrites an earlier verdict.
"""
import json
import os
from pathlib import Path
import signal
import sys
import literal_review_claims as facts
from generic_harness_calibration import digest,require,relative

FALSE_FLAGS=('source_reset','delivery_approval','author_retry_authorized','review_override','semantic_approval','historical_tdd_red')
TOKENS={basis+'.'+predicate+'='+str(value).lower():(basis,predicate,value)
    for basis in facts.PAIRS for predicate in ('line_changed','outside_literal') for value in (True,False)}
FINDING_FIELDS={'kind','tree','path','test','line','quote','expected','observed'}


def validate_decision(value):
    require(isinstance(value,dict) and set(value)=={'action','reason','optional_files','findings'}
        and value['action'] in ('request_review_reconsideration','request_test_revision','escalate_cto')
        and isinstance(value['reason'],str) and 1<=len(value['reason'])<=1200
        and value['optional_files']==[] and isinstance(value['findings'],list) and len(value['findings'])<=3)
    if value['action']!='escalate_cto':require(value['findings'])
    for finding in value['findings']:
        require(isinstance(finding,dict) and set(finding)==FINDING_FIELDS
            and finding['tree'] in ('candidate','previous') and type(finding['line']) is int and finding['line']>0
            and all(isinstance(finding[k],str) and 1<=len(finding[k])<=500 for k in ('kind','path','test','quote','expected','observed')))
        if value['action']=='request_review_reconsideration':
            require(finding['kind']=='review_disagreement' and finding['test']=='__module__'
                and finding['expected'] in TOKENS and finding['observed'] in TOKENS)
            before,after=TOKENS[finding['expected']],TOKENS[finding['observed']]
            require(before[:2]==after[:2] and before[2] is not after[2])
    return value


def assess(original,seed,candidate,manifests,path,decision):
    validate_decision(decision);require(decision['action']=='request_review_reconsideration');relative(path)
    roots=dict(original=Path(original),seed=Path(seed),candidate=Path(candidate));claims=[];observed=[]
    require(isinstance(manifests,dict) and set(manifests)==set(roots))
    # Verify all sources before reading a finding, not just the source it cites.
    for name,root in roots.items():facts.probe(root,manifests[name])
    for finding in decision['findings']:
        selection={('candidate',path):'candidate',('previous','original/'+path):'original',('previous','seed/'+path):'seed'}
        tree=selection.get((finding['tree'],finding['path']));require(tree)
        data=(roots[tree]/path).read_bytes();require(len(data)<=32768)
        lines=data.splitlines();require(1<=finding['line']<=len(lines));line=lines[finding['line']-1].decode()
        quote=finding['quote'];require('\n' not in quote and '\r' not in quote and line.count(quote)==1)
        basis,predicate,expected_observation=TOKENS[finding['observed']]
        claims.append(dict(basis=basis,tree=tree,path=path,line=finding['line'],column=line.index(quote)+1,
            quote=quote,predicate=predicate));observed.append(expected_observation)
    measured=facts.assess(original,seed,candidate,manifests,path,claims)
    contradicted=[i for i,(entry,expected) in enumerate(zip(measured['claims'],observed)) if entry['supported'] is not expected]
    return dict(operation='literal_review_finding_assessment_v1',decision_sha256=digest(decision),source_manifests=manifests,
        facts=measured,factual_disagreement_verified=not contradicted,contradicted_findings=contradicted,
        model_calls=0,**{k:False for k in FALSE_FLAGS},
        limitation='Only the new structured CTO findings are checked. Earlier prose is preserved, not converted or overridden.')


def main(args):
    try:
        require(len(args)==6);signal.alarm(120)
        require(not Path('/var/run/docker.sock').exists()
            and not any(os.environ.get(k) for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN')))
        original,seed,candidate,manifests,path,decision=args
        require(len(manifests)<=1024 and len(decision)<=32768)
        result=assess(original,seed,candidate,json.loads(manifests,object_pairs_hook=facts.unique),path,
            json.loads(decision,object_pairs_hook=facts.unique))
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as error:
        print(json.dumps(dict(operation='literal_review_finding_assessment_v1',failure=type(error).__name__,
            model_calls=0,**{k:False for k in FALSE_FLAGS})));return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
