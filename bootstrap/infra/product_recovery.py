"""Shared recovery contracts: bounded dependency requests and test preservation."""
import json,re
from product_workspace import digest

CONFIGS=('package.json','package-lock.json','tsconfig.json','tsconfig.build.json','eslint.config.mjs')
def is_test(name):return name.startswith('tests/') or bool(re.search(r'\.(test|spec)\.[cm]?[jt]sx?$',name))
def dependencies(spec):
    if not isinstance(spec,dict) or set(spec)!={'dependencies','devDependencies'}:raise ValueError('explicit dependency maps required')
    if any(not isinstance(v,dict) for v in spec.values()):raise ValueError('dependency map required')
    count=sum(len(v) for v in spec.values())
    if count>8:raise ValueError(f'dependency delta limit: received {count} packages, maximum 8. Send only additions or version changes, not the full package.json. Omitted existing dependencies are preserved. Use exact semver, not ^ or ~ ranges.')
    for group,items in spec.items():
        if not isinstance(items,dict):raise ValueError('dependency map required')
        for name,version in items.items():
            if not isinstance(name,str) or not re.fullmatch(r'(?:@[a-z0-9-]+/)?[a-z0-9][a-z0-9._-]*',name) or not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?',version):raise ValueError('registry package and exact semver only; no URLs, tags or scripts')
    if set(spec['dependencies']) & set(spec['devDependencies']):raise ValueError('duplicate dependency')
    return spec
def request_spec(spec):
    if not isinstance(spec,dict) or set(spec)!={'brief','dependencies','devDependencies'} or not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=10000:raise ValueError('actionable original-author brief required')
    dependencies({k:spec[k] for k in ('dependencies','devDependencies')});return spec
def apply_dependencies(original,spec):
    dependencies(spec);p=json.loads(original)
    required={'test':'vitest run','lint':'eslint server tests','typecheck':'tsc --noEmit','build':'tsc -p tsconfig.build.json'}
    if any(p.get('scripts',{}).get(k)!=v for k,v in required.items()):raise PermissionError('validation command contract changed')
    for group,items in spec.items():p.setdefault(group,{}).update(items)
    return json.dumps(p,indent=2)+'\n'
def recovery_key(pub,cause):return 'recovery-v2:'+digest(dict(pr=pub['pr'],head=pub['head'],cause=cause))

def ready_dependencies(files,spec,required):
    package=json.loads(files['package.json'])
    missing=[]
    for group,names in required.items():
        for name in names:
            if name not in spec[group] and name not in package.get(group,{}):missing.append(group+':'+name)
    if missing:raise ValueError('Unresolved prerequisites: '+', '.join(missing)+'. Supply exact versions now; do not defer approval to the implementer.')
