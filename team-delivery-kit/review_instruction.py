"""Lossless JSON presentation compaction; never truncate review requirements."""
import json


def bounded(text, limit=2500):
    if not isinstance(text, str) or not text:
        raise ValueError('review instruction required')
    if len(text) <= limit:
        return text
    decoder = json.JSONDecoder()
    parts, offset = [], 0
    while offset < len(text):
        if text[offset] in '[{':
            try:
                value, end = decoder.raw_decode(text, offset)
            except ValueError:
                pass
            else:
                parts.append(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
                offset = end
                continue
        parts.append(text[offset])
        offset += 1
    result = ''.join(parts)
    if len(result) > limit:
        raise ValueError('review instruction exceeds route limit; split context without losing criteria')
    return result
