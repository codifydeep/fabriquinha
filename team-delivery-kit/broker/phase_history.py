"""Decode one controller phase envelope without interpreting quoted history."""
import json

ENVELOPES={
    'CURRENT TASK: R1 NEW-TEST HARNESS REPAIR ONLY.\n':'ORIGINAL BRIEF DATA: ',
    'CURRENT TASK: R2 PRODUCT ONLY.\n':'ORIGINAL BRIEF DATA: ',
    'CURRENT REVIEW: independent immutable product delivery for R2.\n':'ORIGINAL REVIEW DATA: ',
}


def decode(text, prefix, marker):
    if ENVELOPES.get(prefix)!=marker or not isinstance(text,str) or not text.startswith(prefix):
        raise ValueError('exact controller phase envelope required')
    # JSON strings escape newlines. A marker inside that string is historical
    # DATA, not another delimiter. Ambiguous multiple top-level records remain
    # rejected instead of silently selecting one of them.
    delimiter='\n'+marker
    if text.count(delimiter)!=1:raise ValueError('one line-delimited phase history required')
    _,_,tail=text.partition(delimiter)
    try:item,end=json.JSONDecoder().raw_decode(tail)
    except (ValueError,TypeError) as error:raise ValueError('complete JSON-quoted phase history required') from error
    if not isinstance(item,str) or not item.strip() or tail[end:].strip():
        raise ValueError('complete lossless historical data required')
    return item
