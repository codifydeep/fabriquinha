"""Structural evidence for an additive fixture repair, not repair authority.

Never execute candidate code. This comparison cannot establish semantic safety:
existing helper calls may have side effects. Exact independent review and fresh
behavioral Red/Green/negative controls remain necessary before a new freeze.
No installed gate currently grants an exception from this result alone.
"""
import ast
import copy
import difflib


def shape(node):
    return ast.dump(node,include_attributes=False)


def fixture_diff(before,after):
    """Keep every old statement; identify additive setup, including resource scopes.

    Existing imported functions and methods may be used. Calls are not semantic
    proof: independent review and execution remain necessary. New with blocks
    can contain new setup only; they cannot wrap any preserved assertion.
    """
    left=ast.parse(before);right=ast.parse(after)
    imported={alias.asname or alias.name.split('.')[0] for node in left.body
              if isinstance(node,(ast.Import,ast.ImportFrom)) for alias in node.names if alias.name!='*'}
    def methods(tree):
        return {(cls.name,method.name):method for cls in tree.body if isinstance(cls,ast.ClassDef)
                for method in cls.body if isinstance(method,ast.FunctionDef) and method.name.startswith('test')}
    old,new=methods(left),methods(right)
    if old.keys()!=new.keys():raise ValueError('test inventory changed')
    result={}
    for key,prior in old.items():
        current=new[key];index=0;added=[]
        existing={node.id for node in ast.walk(prior) if isinstance(node,ast.Name)}
        fresh=set()
        def bind(target):
            names=([target.id] if isinstance(target,ast.Name) else
                   [n.id for n in target.elts if isinstance(n,ast.Name)] if isinstance(target,ast.Tuple) else [])
            if (not names or isinstance(target,ast.Tuple) and len(names)!=len(target.elts)
                    or len(set(names))!=len(names) or set(names)&(existing|fresh|imported)):
                raise ValueError('fixture revision cannot rebind or mutate existing names')
            fresh.update(names)
        def call(expression):
            if not isinstance(expression,ast.Call):raise ValueError('fixture call required')
            for node in ast.walk(expression):
                if isinstance(node,(ast.Lambda,ast.NamedExpr,ast.Await,ast.Yield,ast.YieldFrom,
                                    ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
                    raise ValueError('fixture cannot introduce hidden execution flow')
                if isinstance(node,ast.Call):
                    if isinstance(node.func,ast.Name):
                        if node.func.id not in imported:raise ValueError('only existing imported functions may be called directly')
                    elif isinstance(node.func,ast.Attribute):
                        if node.func.attr.startswith('__') or node.func.attr in ('skipTest','fail','stopTest','addCleanup'):
                            raise ValueError('test control calls prohibited')
                    else:raise ValueError('fixture method or existing imported function required')
        def setup(statement):
            if isinstance(statement,ast.Assign):
                if len(statement.targets)!=1:raise ValueError('one fresh fixture assignment required')
                bind(statement.targets[0]);call(statement.value)
            elif isinstance(statement,ast.Expr):call(statement.value)
            elif isinstance(statement,ast.With):
                for item in statement.items:
                    call(item.context_expr)
                    if item.optional_vars is not None:bind(item.optional_vars)
                for nested in statement.body:setup(nested)
            else:raise ValueError('only additive fixture setup statements permitted')
        for statement in current.body:
            if index<len(prior.body) and shape(statement)==shape(prior.body[index]):
                index+=1;continue
            setup(statement);added.append(ast.get_source_segment(after,statement))
        if index!=len(prior.body):raise ValueError('existing test statement changed or removed')
        if added:result['.'.join(key)]=added
        current.body=copy.deepcopy(prior.body)
    if shape(left)!=shape(right):raise ValueError('fixture repair cannot alter module, helper or test definition')
    if not result:raise ValueError('nonempty additive fixture revision required')
    return result


def candidate_diff(before,after):
    """Bounded review evidence, not a proof of semantic equivalence."""
    left,right=ast.parse(before),ast.parse(after)
    def cases(tree):
        return {(cls.name,node.name):node for cls in tree.body if isinstance(cls,ast.ClassDef)
                for node in cls.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name.startswith('test')}
    old,new=cases(left),cases(right)
    if old.keys()!=new.keys():raise ValueError('test inventory changed')
    def assertions(node):
        return sum(isinstance(n,ast.Assert) or isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                   and n.func.attr.startswith('assert') for n in ast.walk(node))
    for key in old:
        if assertions(new[key])<assertions(old[key]):raise ValueError('candidate removed assertions')
    prohibited={'skip','skipIf','skipUnless','skipTest','expectedFailure','load_tests','__unittest_skip__','__unittest_expecting_failure__'}
    for node in ast.walk(right):
        if isinstance(node,ast.Name) and node.id in prohibited or isinstance(node,ast.Attribute) and node.attr in prohibited:
            raise ValueError('candidate cannot suppress test execution')
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name=='load_tests':
            raise ValueError('candidate cannot change discovery')
    diff=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='previous',tofile='candidate'))
    if not diff or len(diff)>24000:raise ValueError('bounded complete candidate diff required; split the correction')
    try:structural=dict(additive=True,findings=fixture_diff(before,after))
    except ValueError as error:structural=dict(additive=False,reason=str(error))
    return dict(diff=diff,structural=structural,semantic_review_required=True)


def technical_repair_diff(before, after, *, cases=None):
    """Evidence for the stricter technical-repair contract, never authority.

    Preserve assertion expressions and their enclosing control flow. Setup and
    action changes still require independent semantic review and negative tests.
    Kept separate so historical candidate receipts retain their original rules.
    """
    findings = candidate_diff(before, after)
    left, right = ast.parse(before), ast.parse(after)
    def methods(tree):
        return {cls.name+'.'+method.name:method for cls in tree.body if isinstance(cls,ast.ClassDef)
                for method in cls.body if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef))
                and method.name.startswith('test')}
    old, new = methods(left), methods(right)
    allowed = set(old) if cases is None else set(cases)
    if not allowed or not allowed <= set(old):raise ValueError('exact existing scoped test methods required')
    for name in allowed:
        prior,current=old[name],new[name]
        before_exits=[shape(n) for n in ast.walk(prior) if isinstance(n,(ast.Return,ast.Raise,ast.Break,ast.Continue))]
        after_exits=[shape(n) for n in ast.walk(current) if isinstance(n,(ast.Return,ast.Raise,ast.Break,ast.Continue))]
        if before_exits!=after_exits:raise ValueError('technical repair cannot add or change early exits')
        current.body=copy.deepcopy(prior.body)
    if shape(left)!=shape(right):
        raise ValueError('technical repair cannot change unscoped cases, helpers, imports or test definitions')

    def protected(tree):
        result = []

        def control(node):
            if isinstance(node,(ast.If,ast.While)):return shape(node.test)
            if isinstance(node,(ast.For,ast.AsyncFor)):return shape(node.target)+shape(node.iter)
            if isinstance(node,(ast.With,ast.AsyncWith)):return repr([shape(item) for item in node.items])
            if isinstance(node,ast.ExceptHandler):return shape(node.type) if node.type else 'bare'
            return ''

        def visit(node, context):
            assertion = isinstance(node, ast.Assert) or (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith('assert'))
            if assertion:
                result.append((context, shape(node)))
                return
            for field, value in ast.iter_fields(node):
                if isinstance(value, list):
                    for child in value:
                        if isinstance(child, ast.AST):
                            visit(child, context + ((type(node).__name__, field, control(node)),))
                elif isinstance(value, ast.AST):
                    visit(value, context + ((type(node).__name__, field, control(node)),))

        for cls in tree.body:
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test'):
                        visit(method, ((cls.name, method.name),))
        return result

    if protected(ast.parse(before)) != protected(ast.parse(after)):
        raise ValueError('technical repair must preserve assertion expressions and control nesting')
    return findings


def fixture_snapshot_diff(store,before,after,paths,tests_dir,*,candidate=False):
    """Bound structural findings to the exact proposed snapshot and paths.

    The caller must still verify the independently approved correction proposal;
    this function supplies no authority and writes no receipt or snapshot.
    """
    from pathlib import PurePosixPath
    left,right=store.manifest(before),store.manifest(after)
    if (not isinstance(paths,list) or not 1<=len(paths)<=20 or any(not isinstance(p,str) for p in paths)
            or len(set(paths))!=len(paths)):
        raise ValueError('explicit distinct existing acceptance paths required')
    for path in paths:
        item=PurePosixPath(path)
        if (str(item)!=path or item.parent.as_posix()!=tests_dir or not item.name.startswith('acceptance_')
                or item.suffix!='.py' or path not in left or path not in right):
            raise ValueError('only existing direct acceptance Python files eligible')
    changed={p for p in set(left)|set(right) if left.get(p)!=right.get(p)}
    if not changed or not changed<=set(paths):raise ValueError('only proposed fixture files may change')
    result={}
    for path in sorted(changed):
        if left[path]['executable']!=right[path]['executable']:
            raise ValueError('fixture file mode must remain unchanged')
        result[path]=(candidate_diff if candidate else fixture_diff)((store.tree(before)/path).read_text(),(store.tree(after)/path).read_text())
    if candidate and sum(len(item['diff']) for item in result.values())>24000:
        raise ValueError('bounded complete candidate diff required; split the correction')
    return result


def protect_repaired_baseline(project, store, baseline, candidate, paths):
    """Only scoped existing test substitutions; never configuration exceptions."""
    from .artifacts import protected_unchanged
    from .quality import PROTECTED
    left,right=store.manifest(baseline),store.manifest(candidate)
    protected_unchanged(left,right,prefixes=PROTECTED)
    protected_unchanged(right,left,prefixes=PROTECTED)
    prefix=project.tests_dir+'/'
    for path,value in left.items():
        if path.startswith(prefix) and right.get(path)!=value:
            if path not in paths or path not in right or right[path]['executable']!=value['executable']:
                raise ValueError('unscoped baseline test changed or removed')


def repaired_baseline(store, baseline, candidate, paths):
    """Controller-owned baseline copy, retaining original product and inventory."""
    import tempfile
    from pathlib import Path
    original=store.manifest(baseline)
    eligible=[p for p in paths if p in original]
    if not eligible:return baseline
    with tempfile.TemporaryDirectory(prefix='.test-repair-baseline-',dir=store.root.parent) as folder:
        work=Path(folder);store.checkout(baseline,work)
        for path in eligible:(work/path).write_bytes((store.tree(candidate)/path).read_bytes())
        return store.capture(work)


def verify_repaired_baseline(store, baseline, candidate, paths, repaired):
    expected=dict(store.manifest(baseline));right=store.manifest(candidate)
    for path in paths:
        if path in expected:expected[path]=right[path]
    if store.manifest(repaired)!=expected:raise ValueError('exact scoped baseline projection required')


def revision_context(project,store,quality,authority,candidate,*,contract=1):
    """Read independently reviewed authority; return the original Red baseline.

    Only unpublished fixture corrections with the unchanged product qualify.
    This does not approve the candidate or the delivery.
    """
    context=authority['context']
    if context.get('repair_kind')!='fixture' or authority['proposal']['classification']!='test_contract':
        raise ValueError('independently reviewed fixture proposal required')
    freeze=store.receipt(context['tests'],kind='tests_frozen')
    previous=quality.frozen_plan(freeze)
    review=store.receipt(authority['review'])
    if review['kind'] not in ('plan_review','test_repair_admission'):raise ValueError('test repair authority required')
    if (context['snapshot']!=previous['snapshot']
            or freeze['binding']['release']!=review['binding']['release']):
        raise ValueError('fixture source must be the exact old freeze')
    if type(contract) is not int or contract not in (1,2,3):raise ValueError('unknown candidate revision contract')
    if (review['kind']=='test_repair_admission')!=(contract==3):
        raise ValueError('technical repair authority requires contract 3; historical contracts remain unchanged')
    fixture_snapshot_diff(store,previous['snapshot'],candidate,authority['proposal']['test_paths'],project.tests_dir,candidate=contract in (2,3))
    if contract==3:
        if review['kind']!='test_repair_admission':raise ValueError('structured CTO authority required')
        for path in authority['proposal']['test_paths']:
            before=(store.tree(previous['snapshot'])/path).read_text()
            after=(store.tree(candidate)/path).read_text()
            if before!=after:
                from pathlib import PurePosixPath
                prefix=PurePosixPath(path).stem+'.'
                technical_repair_diff(before,after,cases=[c[len(prefix):] for c in context['cases'] if c.startswith(prefix)])
    if contract==3:
        protect_repaired_baseline(project,store,previous['baseline'],candidate,authority['proposal']['test_paths'])
    else:quality.protect(previous['baseline'],candidate)
    return previous


def verify_red_revision(project,store,quality,record):
    """Recheck new Red's provenance and preserve the old control target set."""
    from .repairs import reviewed
    value=record['payload'];revision=value['fixture_revision']
    shapes=({'authority','tests'},{'authority','tests','contract'})
    if isinstance(revision,dict) and revision.get('contract')==3:
        shapes=(*shapes,{'authority','tests','contract','repaired_baseline','original_baseline_job'})
    if not isinstance(revision,dict) or set(revision) not in shapes:
        raise ValueError('exact fixture provenance required')
    authority=reviewed(project,store,revision['authority'])
    previous=revision_context(project,store,quality,authority,value['snapshot'],contract=revision.get('contract',1))
    review=store.receipt(revision['authority'])
    old=store.receipt(revision['tests'],kind='tests_frozen')
    if (record['kind']!='red' or record['binding']['kind']!='tests' or record['binding']['reviewing']
            or record['binding']['release']!=review['binding']['release']
            or old['binding']['release']!=record['binding']['release']
            or revision['tests']!=authority['context']['tests']
            or value['project']!=project.fingerprint() or value['baseline']!=previous['baseline']
            or set(value['cases'])!=set(previous['cases']) or set(value['new_cases'])!=set(previous['new_cases'])):
        raise ValueError('new Red must preserve the exact reviewed fixture scope and inventory')
    if revision.get('contract')==3:
        from .quality import suite_report, preview_evidence
        corrected=revision.get('repaired_baseline',value['baseline'])
        verify_repaired_baseline(store,value['baseline'],value['snapshot'],authority['proposal']['test_paths'],corrected)
        if corrected!=value['baseline']:
            reports=[]
            for key,snapshot in ((revision['original_baseline_job'],value['baseline']),(value['baseline_job'],corrected)):
                job=store.receipt(key,kind='suite_job');data=job['payload'];identity=data['identity']
                if (job['binding']!=record['binding'] or identity['binding']!=record['binding']
                        or identity['snapshot']!=snapshot or identity['phase']!='baseline'
                        or identity['project']!=project.fingerprint() or identity['image']!=project.validation_image
                        or data['sandbox']!=dict(network='none',snapshot='readonly',user='65534:65534')):
                    raise ValueError('exact isolated baseline repair observations required')
                preview_evidence(project,store,data,snapshot,'baseline')
                reports.append(suite_report(data))
            original,current=reports
            if (current['failures'] or set(current['cases'])!=set(original['cases'])
                    or not {f['case'] for f in original['failures']}<=set(authority['context']['cases'])):
                raise ValueError('baseline repair must preserve and pass all existing cases')
    targets=set(previous['control_cases'])
    if revision.get('contract')==3:
        targets.update(authority['context']['cases'])
    return targets


def implementation_seed(project,store,quality,authority,frozen):
    """Carry product work forward only after the revised tests are frozen.

    Never edit the old worker or old snapshot. The returned immutable snapshot
    combines preserved product work with the independently frozen exact tests.
    """
    import tempfile
    from pathlib import Path
    context=authority['context']
    red=store.receipt(frozen['red'],kind='red')
    revision=red['payload'].get('fixture_revision',{})
    if ({k:revision.get(k) for k in ('authority','tests')}!=dict(authority=authority['review'],tests=context['tests'])
            or red['payload']['snapshot']!=frozen['snapshot']):
        raise ValueError('exact independently frozen fixture revision required for product seed')
    revision_context(project,store,quality,authority,frozen['snapshot'],contract=revision.get('contract',1))
    source=context['implementation_snapshot']
    quality.protect(context['snapshot'],source,exact_tests=True)
    with tempfile.TemporaryDirectory(prefix='.fixture-seed-',dir=store.root.parent) as folder:
        work=Path(folder);store.checkout(source,work)
        for path in authority['proposal']['test_paths']:
            (work/path).write_bytes((store.tree(frozen['snapshot'])/path).read_bytes())
        snapshot=store.capture(work)
    quality.protect(frozen['snapshot'],snapshot,exact_tests=True)
    return snapshot
