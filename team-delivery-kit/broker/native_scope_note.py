"""Decode only the known Multica one-shot time envelope for scope tasks.

This is not authorization: callers must still authenticate the task, wakeup,
actor, issue, exact registered instruction and immutable scope evidence.
Unknown or changed envelopes fail closed; never search for a trusted substring.
"""
import datetime
import json
import re


def canonical(note, wakeup_id):
    if not isinstance(note,str):raise ValueError('scope note text required')
    if not note.startswith('Wakeup '):return note
    prefix='Wakeup '+str(wakeup_id)+' triggered. Instruction:\n'
    footer='\nTrigger facts (read current state before deciding what to do):\ntime.due '
    if not note.startswith(prefix) or note.count(footer)!=1 or not note.endswith('\n'):
        raise ValueError('exact scope wakeup envelope required')
    body,facts=note[len(prefix):-1].split(footer)
    if not body or '\n' in facts:raise ValueError('single scope time fact required')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate scope fact')
            result[key]=value
        return result
    fact=json.loads(facts,object_pairs_hook=unique)
    if (not isinstance(fact,dict) or set(fact)!={'kind','planned_at'} or fact['kind']!='at'
            or not isinstance(fact['planned_at'],str)
            or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z',fact['planned_at'])):
        raise ValueError('exact scope time fact required')
    datetime.datetime.fromisoformat(fact['planned_at'].replace('Z','+00:00'))
    return body
