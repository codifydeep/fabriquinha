"""Check structured source-location claims, never free-text review semantics.

A supported or contradicted claim is evidence only. Neither result approves a
delivery, changes a verdict, retries a worker, or proves semantic correctness.
Comparison basis is explicit so inherited edits cannot become current edits.
"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
from generic_harness_calibration import digest,require,relative
from r3_snapshot_probe import probe

PAIRS={'original_to_seed':('original','seed'),'seed_to_candidate':('seed','candidate'),
    'original_to_candidate':('original','candidate')}
FIELDS={'basis','tree','path','line','column','quote','predicate'}
CLAIM_SCHEMA=dict(type='array',minItems=1,maxItems=3,items=dict(type='object',additionalProperties=False,
    required=sorted(FIELDS),properties=dict(
        basis=dict(type='string',enum=list(PAIRS)),tree=dict(type='string',enum=['original','seed','candidate']),
        path=dict(type='string',minLength=1,maxLength=240),line=dict(type='integer',minimum=1),
        column=dict(type='integer',minimum=1),quote=dict(type='string',minLength=1,maxLength=500),
        predicate=dict(type='string',enum=['line_changed','outside_literal']))))


def sha(raw):return hashlib.sha256(raw).hexdigest()


def unique(pairs):
    result={}
    for k,v in pairs:
        require(k not in result);result[k]=v
    return result


def line_delta(before,after):
    old,new=before.splitlines(keepends=True),after.splitlines(keepends=True)
    require(len(old)<=4096 and len(new)<=4096)
    matcher=difflib.SequenceMatcher(a=old,b=new,autojunk=False);a=[];b=[];hunks=[]
    for tag,i,j,k,l in matcher.get_opcodes():
        if tag=='equal':continue
        hunks.append(dict(kind=tag,old_start=i+1,old_count=j-i,new_start=k+1,new_count=l-k))
        require(len(hunks)<=64)
        a.extend(range(i+1,j+1));b.extend(range(k+1,l+1))
    return dict(old_changed_lines=a,new_changed_lines=b,hunks=hunks)


def validate_claim(claim,path,raw):
    require(isinstance(claim,dict) and set(claim)==FIELDS)
    require(isinstance(claim['basis'],str) and claim['basis'] in PAIRS
        and isinstance(claim['tree'],str) and claim['tree'] in PAIRS[claim['basis']]
        and claim['path']==path and claim['predicate'] in ('line_changed','outside_literal'))
    require(type(claim['line']) is int and type(claim['column']) is int and claim['column']>=1
        and isinstance(claim['quote'],str) and 1<=len(claim['quote'])<=500 and claim['quote'].strip()
        and '\n' not in claim['quote'] and '\r' not in claim['quote'])
    data=raw[claim['tree']];lines=data.splitlines(keepends=True)
    require(1<=claim['line']<=len(lines));line=lines[claim['line']-1].decode('utf-8').rstrip('\r\n')
    offset=claim['column']-1;require(line[offset:offset+len(claim['quote'])]==claim['quote'])
    start=sum(len(v) for v in lines[:claim['line']-1])+len(line[:offset].encode())
    return start,start+len(claim['quote'].encode())


def assess(original,seed,candidate,manifests,path,claims):
    from literal_test_maintenance import slot
    relative(path);require(path.endswith('.py') and isinstance(manifests,dict)
        and set(manifests)=={'original','seed','candidate'} and isinstance(claims,list) and 1<=len(claims)<=3)
    roots=dict(original=Path(original),seed=Path(seed),candidate=Path(candidate));raw={};slots={};ranges={}
    for name,root in roots.items():
        probe(root,manifests[name]);data=(root/path).read_bytes();raw[name]=data;slots[name]=slot(data,'NODE_HARNESS')
        start=len(slots[name]['prefix']);end=len(data)-len(slots[name]['suffix'])
        ranges[name]=dict(start_byte=start,end_byte_exclusive=end,test_sha256=sha(data))
    comparisons={}
    for basis,(a,b) in PAIRS.items():
        comparisons[basis]=dict(line_delta(raw[a],raw[b]),old_tree=a,new_tree=b,
            outside_literal_bytes_preserved=slots[a]['prefix']==slots[b]['prefix'] and slots[a]['suffix']==slots[b]['suffix'])
    results=[]
    for claim in claims:
        start,end=validate_claim(claim,path,raw)
        tree=claim['tree'];span=ranges[tree];within=span['start_byte']<=start and end<=span['end_byte_exclusive']
        pair=comparisons[claim['basis']];which='old' if tree==pair['old_tree'] else 'new'
        changed=claim['line'] in pair[which+'_changed_lines']
        # A quote straddling the literal boundary is outside the allowed slot;
        # never turn a partial overlap into proof of full scope compliance.
        supported=changed if claim['predicate']=='line_changed' else not within
        results.append(dict(claim=claim,claim_sha256=digest(claim),supported=supported,
            status='supported' if supported else 'contradicted',line_changed=changed,quote_entirely_inside_literal=within))
    for name,root in roots.items():probe(root,manifests[name])
    return dict(operation='literal_review_claim_facts_v1',source_manifests=manifests,test_path=path,
        literal='NODE_HARNESS',literal_spans=ranges,comparisons=comparisons,claims=results,model_calls=0,
        **{k:False for k in ('source_reset','delivery_approval','author_retry_authorized','review_override','semantic_approval','historical_tdd_red')},
        limitation='Location, line-diff and literal-span facts only. No interpretation of free prose or semantic approval.')


def main(args):
    try:
        require(len(args)==6);signal.alarm(120)
        require(not Path('/var/run/docker.sock').exists()
            and not any(os.environ.get(k) for k in ('OPENROUTER_API_KEY','OPENAI_API_KEY','GITHUB_TOKEN','GH_TOKEN')))
        original,seed,candidate,manifests,path,claims=args
        require(len(manifests)<=1024 and len(claims)<=8192)
        result=assess(original,seed,candidate,json.loads(manifests,object_pairs_hook=unique),path,
            json.loads(claims,object_pairs_hook=unique))
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as error:
        print(json.dumps(dict(operation='literal_review_claim_facts_v1',failure=type(error).__name__,
            source_reset=False,delivery_approval=False,review_override=False,model_calls=0)));return 1


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
