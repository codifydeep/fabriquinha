"""Untrusted upstream error bodies become hashes and fixed lexical hints only."""
import hashlib
import json

MARKERS=('additionalproperties','anyof','context','invalid','maxitems','messages',
         'oneof','parameter','required','schema','strict','tool_choice','tool_result',
         'tool_use','unsupported')


def describe(raw):
    message='';valid=False
    try:
        value=json.loads(raw)
        error=value.get('error') if isinstance(value,dict) else None
        if isinstance(error,dict) and isinstance(error.get('message'),str):
            message=error['message'].lower();valid=True
            metadata=error.get('metadata')
            nested=metadata.get('raw') if isinstance(metadata,dict) else None
            if isinstance(nested,str):message+=' '+nested.lower()
    except (ValueError,UnicodeDecodeError):pass
    return {'version':'upstream-request-rejection-v1','response_sha256':hashlib.sha256(raw).hexdigest(),
            'json_error':valid,'markers':[m for m in MARKERS if m in message]}


class UpstreamRequestRejected(Exception):
    def __init__(self,raw):
        super().__init__('upstream request rejected')
        self.status=400
        self.diagnostic=describe(raw)
