"""One typed authenticated local POST, observed from two existing browser contexts."""
import ast
import keyword
import re

from .test_revision import candidate_diff,shape


def name(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z][A-Za-z_0-9]{0,63}',value) or keyword.iskeyword(value):
        raise ValueError('probe requires a simple public name')
    return value


def probe_source(spec):
    if set(spec)-{'expected_error'}!={'case','prefix','action','pair','resource','actor','peer','payload'}:
        raise ValueError('closed probe descriptor required')
    if len(spec['case'].split('.'))!=3:
        raise ValueError('exact module.class.case required')
    for part in spec['case'].split('.'):name(part)
    pair=name(spec['pair']); resource=name(spec['resource']); actor=name(spec['actor']);peer=name(spec['peer'])
    if actor==peer or not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/){1,6}',spec['prefix']) or not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',spec['action']):
        raise ValueError('distinct contexts and fixed local route required')
    message_check=()
    if 'expected_error' in spec:
        message=spec['expected_error']
        if not isinstance(message,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .,!?'-]{0,159}",message):
            raise ValueError('bounded literal error message required')
        message_check=(f"self.assertEqual(probe_response.json()['error'], {message!r})",)
    fields=spec['payload']
    if not isinstance(fields,dict) or len(fields)>8:raise ValueError('bounded JSON object required')
    items=[]
    for key,source in sorted(fields.items()):
        if not isinstance(source,list) or len(source)!=2 or type(source[1])!=int or not 0<=source[1]<8:
            raise ValueError('bounded existing indexed data required')
        items.append(f'{name(key)!r}: {name(source[0])}[{source[1]}]')
    return '\n'.join((
        f'probe_url = self.target + {spec["prefix"]!r} + {pair}[{resource!r}]',
        f'probe_actor = {pair}[{actor!r}].context.request',
        f'probe_peer = {pair}[{peer!r}].context.request',
        'probe_actor_before = probe_actor.get(probe_url, max_redirects=0)',
        'probe_peer_before = probe_peer.get(probe_url, max_redirects=0)',
        'self.assertEqual(probe_actor_before.status, 200)',
        'self.assertEqual(probe_peer_before.status, 200)',
        f'probe_response = probe_actor.post(probe_url + {("/"+spec["action"])!r}, data={{{", ".join(items)}}}, max_redirects=0)',
        'self.assertEqual(probe_response.status, 409)',
        *message_check,
        'probe_actor_after = probe_actor.get(probe_url, max_redirects=0)',
        'probe_peer_after = probe_peer.get(probe_url, max_redirects=0)',
        'self.assertEqual(probe_actor_after.status, 200)',
        'self.assertEqual(probe_peer_after.status, 200)',
        'self.assertEqual(probe_actor_after.json(), probe_actor_before.json())',
        'self.assertEqual(probe_peer_after.json(), probe_peer_before.json())',
    ))


def probe_diff(before,after,spec):
    expected=ast.parse(probe_source(spec)).body
    findings=candidate_diff(before,after)
    left,right=ast.parse(before),ast.parse(after)
    _,cls_name,method_name=spec['case'].split('.')
    def locate(tree):
        matches=[method for cls in tree.body if isinstance(cls,ast.ClassDef) and cls.name==cls_name
                 for method in cls.body if isinstance(method,ast.FunctionDef) and method.name==method_name]
        if len(matches)!=1:raise ValueError('unique authorized probe case required')
        return matches[0]
    original,candidate=locate(left),locate(right)
    reserved={n.id for stmt in expected for n in ast.walk(stmt) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    if any(isinstance(n,ast.Name) and n.id in reserved for n in ast.walk(original)):
        raise ValueError('probe would shadow an existing local')
    if [shape(n) for n in candidate.body[len(original.body):]]!=[shape(n) for n in expected]:
        raise ValueError('append the complete authorized HTTP probe verbatim')
    del candidate.body[len(original.body):]
    if shape(left)!=shape(right):raise ValueError('every existing statement and all other cases must be preserved')
    return findings


def check_offer(store,project,key,incident,parent,freeze):
    offer=store.receipt(key,kind='http_probe_offer')
    data=offer['payload'];source=store.receipt(incident,kind='incident')
    if (offer['binding']!={'actor':'controller','release':source['binding']['release']}
            or data['project']!=project.fingerprint() or data['incident']!=incident
            or data['parent']!=parent or data['freeze']!=freeze or data['delivery_approval'] is not False
            or source['binding']['kind']!='tests' or source['binding']['reviewing'] is not False):
        raise ValueError('probe offer must match exact rejected author, parent, release and freeze')
    refusal=store.receipt(source['payload']['submission_refusal'],kind='submission_refusal')
    old=store.receipt(freeze,kind='tests_frozen')['payload']
    if (refusal['binding']!=source['binding'] or refusal['payload']['baseline']!=old['snapshot']
            or refusal['payload']['snapshot']!=source['payload']['snapshot']
            or refusal['payload']['error']!='only explicit product calls and local literal setup allowed'):
        raise ValueError('exact rejected strengthening candidate required')
    trial=store.receipt(data['qualification'],kind='offline_http_probe_qualification')
    proof=trial['payload']
    passed=proof['results']['green'];mutated=proof['results']['mutant']
    if (trial['binding']!=offer['binding'] or proof['project']!=data['project']
            or proof['spec']!=data['spec'] or proof['delivery_approval'] is not False
            or proof['green']==proof['mutant'] or passed!={'count':1,'errors':[],'failures':[]}
            or mutated['count']!=1 or mutated['errors'] or len(mutated['failures'])!=1
            or '200 != 409' not in mutated['failures'][0]):
        raise ValueError('matching offline Green and mutant probe evidence required')
    probe_source(data['spec'])
    return data['spec']
