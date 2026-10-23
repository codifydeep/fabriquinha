"""Bounded, snapshot-bound worker advice; never provenance or approval.

Only the controller's own ACP stream can attest a review. This in-memory
journal keeps actual tool-result pairs available when conversational context
is compacted. It does not execute tools, persist authority, or select a verdict.
"""
import copy
import hashlib
import json
import uuid
from artifact_read_evidence import coverage
try:import quality_review_reads as reads
except ImportError:from broker import quality_review_reads as reads

MAX_PAIRS=512
MAX_BYTES=8*1024*1024
MAX_BATCH=16


def require(value):
    if not value:raise ValueError('bounded snapshot-bound paging evidence required')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Journal:
    def __init__(self,request_id,files,manifest_sha256,read_paths):
        require(isinstance(request_id,str))
        try:canonical=str(uuid.UUID(request_id))
        except (ValueError,TypeError,AttributeError):raise ValueError('canonical review request required') from None
        require(canonical==request_id)
        reads.inventory(files,manifest_sha256,read_paths)
        self.request_id=request_id
        self.manifest_sha256=manifest_sha256
        self._files=copy.deepcopy(files)
        self._paths=tuple(read_paths)
        self._pairs={}
        self._bytes=0

    def add(self,messages,*,max_pairs=MAX_PAIRS,max_bytes=MAX_BYTES):
        """Atomically accept actual paired pages; no eviction or inferred reads.

        A repeated identical call is idempotent. Reusing its identity with
        different arguments/result is corruption, not another page.
        """
        require(type(max_pairs) is int and 0<=max_pairs<=MAX_PAIRS
            and type(max_bytes) is int and 0<=max_bytes<=MAX_BYTES
            and isinstance(messages,list) and len(messages)%2==0
            and len(messages)<=2*MAX_PAIRS)
        additions={};size=self._bytes
        for offset in range(0,len(messages),2):
            pair=messages[offset:offset+2]
            path,_,_=reads.page(pair)
            require(path in self._paths)
            key=pair[0]['call_id']
            encoded=json.dumps(pair,sort_keys=True,separators=(',',':')).encode()
            previous=additions.get(key,self._pairs.get(key))
            if previous is not None:
                require(previous[0]==encoded)
                continue
            size+=len(encoded)
            require(len(self._pairs)+len(additions)+1<=max_pairs and size<=max_bytes)
            additions[key]=(encoded,copy.deepcopy(pair))
        require(len(self._pairs)+len(additions)<=max_pairs and size<=max_bytes)
        self._pairs.update(additions)
        self._bytes=size

    def messages(self):
        return copy.deepcopy([message for _,pair in self._pairs.values() for message in pair])

    def _coverage(self):
        normalized=[];empty=set();totals={};lines={}
        for _,pair in self._pairs.values():
            path,is_empty,parsed=reads.page(pair)
            if is_empty:
                require(path not in totals or totals[path]==0)
                totals[path]=0;empty.add(path);lines.setdefault(path,{})
                continue
            observed=coverage(parsed,include_content=True)
            require(path in observed and path not in empty)
            page=observed[path];total=page['total_lines']
            require(path not in totals or totals[path]==total)
            totals[path]=total
            saved=lines.setdefault(path,{})
            for number,text in page['line_content'].items():
                require(number not in saved or saved[number]==text)
                saved[number]=text
            normalized.extend(parsed)
        found=coverage(normalized,include_content=True)
        require(set(found)==set(totals)-empty)
        for path in empty:
            found[path]=dict(total_lines=0,lines=0,line_content={},next_offset=None)
        return found

    def plan(self,*,required_paths=None):
        required=list(self._paths) if required_paths is None else required_paths
        require(isinstance(required,list) and bool(required)
            and all(isinstance(path,str) for path in required)
            and len(required)==len(set(required)) and set(required)<=set(self._paths))
        observed=self._coverage();cohorts={};complete=[]
        messages=self.messages()
        # Check every complete file, including those outside a rejection's
        # narrower scope. Wrong bytes must stop rather than restart at line 1.
        completed=[path for path,page in observed.items() if page['lines']==page['total_lines']]
        if completed:
            reads.observe(self._files,self.manifest_sha256,list(self._paths),messages,required_paths=completed)
        for path in sorted(required):
            page=observed.get(path)
            if page is not None and page['lines']==page['total_lines']:
                complete.append(path)
                continue
            next_offset=page['next_offset'] if page is not None else 1
            require(type(next_offset) is int and next_offset>=1)
            cohorts.setdefault(next_offset,[]).append(path)
        pages=[]
        if cohorts:
            # One exact offset permits a simple bounded schema/handler plan.
            # Finish the largest independent cohort; ties prefer earlier pages.
            offset=min(cohorts,key=lambda n:(-len(cohorts[n]),n))
            pages=[dict(path=path,offset=offset,limit=100) for path in cohorts[offset][:MAX_BATCH]]
        progress={path:dict(total_lines=page['total_lines'],line_content=page['line_content'])
            for path,page in sorted(observed.items())}
        return dict(request_id=self.request_id,manifest_sha256=self.manifest_sha256,
            pages=pages,required_files=len(required),complete_files=len(complete),
            remaining_files=len(required)-len(complete),
            progress_sha256=digest(dict(request_id=self.request_id,
                manifest_sha256=self.manifest_sha256,observed=progress)),
            tests_approved=False,execution_authorized=False,delivery_approval=False)
