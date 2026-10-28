"""Structural evidence for an additive fixture repair, not repair authority.

Never execute candidate code. This comparison cannot establish semantic safety:
existing helper calls may have side effects. Exact independent review and fresh
behavioral Red/Green/negative controls remain necessary before a new freeze.
No installed gate currently grants an exception from this result alone.
"""
import ast
import copy


def shape(node):
    return ast.dump(node,include_attributes=False)


def fixture_diff(before,after):
    """Keep module structure and every old test statement; identify additions.

    Only straight-line setup using fresh local names and method calls is eligible.
    No assertion/selector/timeout edits, imports, helpers, hooks, discovery changes,
    exception handling, early exits, rebinding or monkeypatch assignment.
    """
    left=ast.parse(before);right=ast.parse(after)
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
        for statement in current.body:
            if index<len(prior.body) and shape(statement)==shape(prior.body[index]):
                index+=1;continue
            if isinstance(statement,ast.Assign):
                targets=statement.targets
                if len(targets)!=1:raise ValueError('one fresh fixture assignment required')
                names=([targets[0].id] if isinstance(targets[0],ast.Name) else
                       [n.id for n in targets[0].elts if isinstance(n,ast.Name)] if isinstance(targets[0],ast.Tuple) else [])
                if (not names or isinstance(targets[0],ast.Tuple) and len(names)!=len(targets[0].elts)
                        or len(set(names))!=len(names) or set(names)&(existing|fresh)):
                    raise ValueError('fixture revision cannot rebind or mutate existing names')
                expression=statement.value;fresh.update(names)
            elif isinstance(statement,ast.Expr):expression=statement.value
            else:raise ValueError('only additive straight-line fixture statements permitted')
            if not isinstance(expression,ast.Call):raise ValueError('fixture method call required')
            for node in ast.walk(expression):
                if isinstance(node,(ast.Lambda,ast.NamedExpr,ast.Await,ast.Yield,ast.YieldFrom,
                                    ast.ListComp,ast.SetComp,ast.DictComp,ast.GeneratorExp)):
                    raise ValueError('fixture cannot introduce hidden execution flow')
                if isinstance(node,ast.Call):
                    if not isinstance(node.func,ast.Attribute):raise ValueError('fixture method calls only')
                    if node.func.attr.startswith('__') or node.func.attr in ('skipTest','fail','stopTest','addCleanup'):
                        raise ValueError('test control calls prohibited')
            added.append(ast.get_source_segment(after,statement))
        if index!=len(prior.body):raise ValueError('existing test statement changed or removed')
        if added:result['.'.join(key)]=added
        current.body=copy.deepcopy(prior.body)
    if shape(left)!=shape(right):raise ValueError('fixture repair cannot alter module, helper or test definition')
    if not result:raise ValueError('nonempty additive fixture revision required')
    return result


def fixture_snapshot_diff(store,before,after,paths,tests_dir):
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
        result[path]=fixture_diff((store.tree(before)/path).read_text(),(store.tree(after)/path).read_text())
    return result
