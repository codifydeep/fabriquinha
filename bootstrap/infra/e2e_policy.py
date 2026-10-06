"""Closed Python fixture policy; not a general-purpose code sandbox."""
import ast
import hashlib

BASELINE='def winner(a, b):\n    return None\n'
NOTES='HTTP score rehearsal. Rule: A if a >= 12, otherwise B if b >= 12, otherwise null. Deployment requires separate verified receipts.\n'
EDITABLE={'app.py','test_user.py','NOTES.md'}


def digest(data): return hashlib.sha256(data).hexdigest()


def baseline_matches(content):
    """Ignore formatting only, never change captured bytes or receipt hashes."""
    validate('app.py',content)
    return ast.dump(ast.parse(content)) == ast.dump(ast.parse(BASELINE))


def validate(name,content):
    if name not in EDITABLE or not isinstance(content,str) or len(content.encode())>12000:
        raise ValueError('only bounded app.py, test_user.py and NOTES.md are editable')
    if name=='NOTES.md':
        if content.strip()!=NOTES.strip(): raise ValueError('notes must use this verified scope: '+NOTES)
        return
    tree=ast.parse(content)
    if name=='app.py':
        if len(tree.body)!=1 or not isinstance(tree.body[0],ast.FunctionDef): raise ValueError('one winner function only')
        fn=tree.body[0]
        if fn.name!='winner' or [a.arg for a in fn.args.args]!=['a','b'] or fn.decorator_list or fn.args.defaults:
            raise ValueError('winner(a,b) only, without decorators/defaults')
        allowed=(ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.If,ast.IfExp,
            ast.Compare,ast.GtE,ast.Gt,ast.Lt,ast.LtE,ast.Eq,ast.NotEq,ast.Name,ast.Load,ast.Constant,
            ast.BoolOp,ast.And,ast.Or)
        if any(not isinstance(n,allowed) for n in ast.walk(tree)): raise ValueError('function contains forbidden syntax')
        if any(isinstance(n,ast.Name) and n.id not in ('a','b') for n in ast.walk(tree)): raise ValueError('unknown name')
        return
    allowed=(ast.Module,ast.Import,ast.ImportFrom,ast.alias,ast.ClassDef,ast.FunctionDef,ast.arguments,
        ast.arg,ast.Expr,ast.Call,ast.Attribute,ast.Name,ast.Load,ast.Constant,ast.If,ast.Compare,ast.Eq)
    if any(not isinstance(n,allowed) for n in ast.walk(tree)): raise ValueError('tests must be direct unittest assertions')
    methods=[]; assertions=0
    for n in ast.walk(tree):
        if isinstance(n,ast.Import) and [(a.name,a.asname) for a in n.names]!=[('unittest',None)]: raise ValueError('only unittest import')
        if isinstance(n,ast.ImportFrom) and (n.module!='app' or n.level or [(a.name,a.asname) for a in n.names]!=[('winner',None)]): raise ValueError('only winner import')
        if isinstance(n,(ast.ClassDef,ast.FunctionDef)) and n.decorator_list: raise ValueError('no test decorators')
        if isinstance(n,ast.FunctionDef):
            if not n.name.startswith('test_') or [a.arg for a in n.args.args]!=['self'] or n.args.defaults: raise ValueError('test methods only')
            methods.append(n.name)
        if isinstance(n,ast.Call):
            f=n.func
            valid=isinstance(f,ast.Name) and f.id=='winner'
            if isinstance(f,ast.Attribute) and isinstance(f.value,ast.Name):
                valid=(f.value.id,f.attr) in [('self','assertEqual'),('self','assertIsNone'),('unittest','main')]
                if f.value.id=='self': assertions+=1
            if not valid or n.keywords: raise ValueError('no executable test hooks')
    if len(set(methods))<5 or len(set(methods))!=len(methods) or assertions<5:
        raise ValueError('at least five distinct test methods/assertions required')
