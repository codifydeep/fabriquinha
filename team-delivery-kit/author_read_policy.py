"""Explicit controller opt-in for bounded revision inspection pages."""
import re


def page_size(body):
    for message in reversed(body.get('messages',[])):
        content=message.get('content','')
        if message.get('role')!='user' or not isinstance(content,str):continue
        revisions=re.findall(r'^DELIVERY_TEST_REVISION_V1:([^\n]+)$',content,re.M)
        pages=re.findall(r'^DELIVERY_AUTHOR_READ_PAGE_V1:([^\n]+)$',content,re.M)
        if not revisions and not pages:continue
        if not pages:return 50
        artifacts=re.findall(r'^DELIVERY_TEST_ARTIFACT_V1:([^\n]+)$',content,re.M)
        sources=re.findall(r'^DELIVERY_TEST_SOURCE_V1:([^\n]+)$',content,re.M)
        if (pages!=['200'] or len(set(revisions))!=1 or set(artifacts)!=set(revisions) or not sources
                or not re.search(r'^DELIVERY_DETERMINISTIC_READ_V1$',content,re.M)
                or re.search(r'^DELIVERY_(?:SURGICAL_TEST|SEEDED_EDIT_REQUIRED|ADDITIVE_CONTROL)_V',content,re.M)):
            raise ValueError('invalid controller author read page capability')
        return 200
    return 50
