"""Managed SDK profiles: one versioned config, controller-only model routing.

Admission reports codes, never config values or credentials. Native loading may
create Hermes's own bounded config backup; this code never repairs/replaces a
profile or treats a last-known-good fallback as a qualified current config.
"""
import json
from pathlib import Path
import re
from .artifacts import digest

MODEL_STORES=('auth.json','.anthropic_oauth.json','.copilot_jwt.json','.op.env','vault')


class ProfileRefused(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)


def configuration():
    # Keep a bounded working window below the qualified provider capacity.
    # 64k forced repeated compaction during a single implementation activity.
    return dict(model={'streaming':False,'context_length':131072},
        auxiliary={'title_generation':{'enabled':False}},tools={'tool_search':{'enabled':'off'}},
        terminal={'backend':'fabriquinha','cwd':'/workspace'})


def contract():
    return digest(dict(version=1,config=configuration(),routing='controller-only',
        effective_policy='inherited-auxiliary-no-fallback-or-extensions'))


def names(project):
    result=set(project.reviewers)
    for author in project.reviewers:result.update(project.reviewers_for(author))
    for roles in (project.technical_roles,project.coordination_roles,project.delivery_roles):result.update((roles or {}).values())
    return sorted(result)


def installation(root):
    path=Path(root)/'installation.json'
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:return {}
        value=json.loads(path.read_bytes())
        return value if isinstance(value,dict) else {}
    except (ValueError,OSError,RecursionError):return {}


def required(project,root):
    return not project.qualification or 'profile_contract' in installation(root)


def unique(pairs):
    value={}
    for key,item in pairs:
        if key in value:raise ValueError('duplicate profile setting')
        value[key]=item
    return value


def native_effective(home):
    from hermes_constants import set_hermes_home_override,reset_hermes_home_override,named_profile_is_live
    from hermes_cli import managed_scope
    from hermes_cli.config import load_config_readonly
    from hermes_cli.config_read_errors import FailedConfigRead
    if not named_profile_is_live(home):raise ProfileRefused('ProfileIdentityUnqualified')
    # Managed overlays/env and credential stores require their own qualification;
    # never override an administrator's policy to make this check pass.
    managed=managed_scope.get_managed_dir()
    if managed and any((managed/name).exists() for name in ('config.yaml','.env')):
        raise ProfileRefused('ProfileManagedScopeUnqualified')
    for folder in (home,home.parent.parent):
        if any((folder/name).exists() or (folder/name).is_symlink() for name in MODEL_STORES):
            raise ProfileRefused('ProfileCredentialsUnqualified')
    token=set_hermes_home_override(home)
    try:
        value=load_config_readonly()
        if isinstance(value,FailedConfigRead):raise ProfileRefused('ProfileConfigFallbackRefused')
        return value  # Borrowed cache object: inspectors must not mutate it.
    finally:reset_hermes_home_override(token)


def effective_errors(value):
    if not isinstance(value,dict):return ['ProfileEffectiveInvalid']
    errors=[]
    expected=configuration()
    for section,key in (('model','streaming'),('model','context_length'),('terminal','backend'),('terminal','cwd')):
        actual=(value.get(section) or {}).get(key) if isinstance(value.get(section),dict) else None
        if type(actual) is not type(expected[section][key]) or actual!=expected[section][key]:errors.append('ProfileEffectiveDrift')
    model=value.get('model') or {}
    if (not isinstance(model,dict) or model.get('provider') not in (None,'','auto')
            or any(model.get(key) not in (None,'') for key in
                   ('default','name','model','base_url','api_base','api_key','api_mode','key_env','api_key_env'))):
        errors.append('ProfileModelRouteUnqualified')
    if any(value.get(key) not in (None,[],{}) for key in ('providers','custom_providers','fallback_providers','hooks')):
        errors.append('ProfileFallbackOrHooksUnqualified')
    tools=value.get('tools') or {};aux=value.get('auxiliary') or {};context=value.get('context') or {};plugins=value.get('plugins') or {}
    if (not isinstance(tools,dict) or not isinstance(tools.get('tool_search'),dict)
            or tools['tool_search'].get('enabled')!='off'):errors.append('ProfileToolPolicyDrift')
    if not isinstance(context,dict) or context.get('engine','compressor')!='compressor':errors.append('ProfileContextEngineUnqualified')
    if not isinstance(plugins,dict) or plugins.get('enabled') not in (None,[]):errors.append('ProfileExtensionsUnqualified')
    memory=value.get('memory') or {}
    if not isinstance(memory,dict) or memory.get('provider') not in (None,''):errors.append('ProfileMemoryUnqualified')
    if (not isinstance(aux,dict) or not isinstance(aux.get('title_generation'),dict)
            or aux['title_generation'].get('enabled') is not False):errors.append('ProfileTitlePolicyDrift')
    def routes(block):
        if not isinstance(block,dict):return
        for key,item in block.items():
            if key=='provider' and item not in (None,'','auto'):errors.append('ProfileAuxiliaryRouteUnqualified')
            if key in ('model','base_url','api_base','api_key','key_env','api_key_env','api_mode','openrouter_model') and item not in (None,''):
                errors.append('ProfileAuxiliaryRouteUnqualified')
            if key in ('fallback_chain','fallback_providers','extra_body','extra_headers') and item not in (None,[],{}):
                errors.append('ProfileAuxiliaryFallbackUnqualified')
            if key=='prefer_fast_model' and item is True:errors.append('ProfileAuxiliaryRouteUnqualified')
            if isinstance(item,dict):routes(item)
    routes(aux)
    return sorted(set(errors))


def inspect_profile(root,name,*,loader=None):
    if not isinstance(name,str) or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',name) or name=='default':
        raise ValueError('explicit named profile required')
    root=Path(root);home=root/'home/profiles'/name;errors=[];checked=False
    try:
        if any(path.is_symlink() for path in (root/'home',root/'home/profiles',home)):
            errors.append('ProfileHomeUnsafe')
        elif not home.is_dir():errors.append('ProfileMissing')
        else:
            path=home/'config.yaml'
            if path.is_symlink() or not path.is_file() or path.stat().st_size>16384 or path.stat().st_mode&0o077:
                errors.append('ProfileConfigUnsafe')
            else:
                raw=json.loads(path.read_bytes(),object_pairs_hook=unique)
                if digest(raw)!=digest(configuration()):errors.append('ProfileConfigDrift')
            for folder in (home,root/'home'):
                if (folder/'auth.json').exists() or (folder/'auth.json').is_symlink():errors.append('ProfileCredentialsUnqualified')
                env=folder/'.env'
                if env.exists() or env.is_symlink():
                    from .github_auth import env_allowed
                    if (env.is_symlink() or not env.is_file() or env.stat().st_size>16384 or env.stat().st_mode&0o077
                            or not env_allowed(root,name if folder==home else None,env.read_text())):
                        errors.append('ProfileCredentialsUnqualified')
                plugins=folder/'plugins'
                if plugins.is_symlink() or plugins.exists() and (not plugins.is_dir() or any(plugins.iterdir())):
                    errors.append('ProfileExtensionsUnqualified')
        if not errors:
            value=(loader or native_effective)(home);checked=True;errors+=effective_errors(value)
    except ProfileRefused as error:errors.append(error.code)
    except ImportError:errors.append('ProfileSDKUnavailable')
    except (ValueError,TypeError,OSError,RecursionError):errors.append('ProfileConfigUnreadable')
    return dict(ready=not errors,errors=sorted(set(errors)),effective_checked=checked,
        contract=contract(),next_action=None if not errors else
        'Restore the managed profile contract under drained maintenance; do not add model credentials to SDK homes.')


def admission(project,root,name):
    if not required(project,root):return dict(ready=True,errors=[],effective_checked=False,contract=None)
    pin=installation(root)
    if pin.get('project')!=project.fingerprint() or pin.get('profile_contract')!=contract():
        return dict(ready=False,errors=['ProfileContractRequired'],effective_checked=False,contract=None)
    try:return inspect_profile(root,name)
    except ValueError:return dict(ready=False,errors=['ProfileIdentityUnqualified'],effective_checked=False,contract=contract())


def report(project,root):
    if not required(project,root):return dict(contract=None,errors=[],profiles={})
    pin=installation(root)
    if pin.get('project')!=project.fingerprint() or pin.get('profile_contract')!=contract():
        return dict(contract=None,errors=['ProfileContractRequired'],profiles={})
    owner=(project.delivery_roles or {}).get('integration') or (project.technical_roles or {}).get('lead') or 'operator'
    return dict(contract=contract(),errors=[],profiles={name:{**admission(project,root,name),'technical_owner':owner}
        for name in names(project)})
