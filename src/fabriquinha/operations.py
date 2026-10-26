"""Persistent operational fence and read-only admission, never delivery state."""
from contextlib import contextmanager
import fcntl
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from .effects import EffectBlocked, NotSent, write_json
from .executor import Runner, docker,validation_files
from .kanban_lane import UPSTREAM_COMMIT


class ActivityPaused(EffectBlocked,NotSent):pass


class Control:
    def __init__(self,root,project):
        self.root,self.project=Path(root),project
        self.path=self.root/'control.json'

    @contextmanager
    def lock(self):
        with (self.root/'control.lock').open('a') as file:
            fcntl.flock(file,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(file,fcntl.LOCK_UN)

    def read(self):
        try:
            info=self.path.lstat()
            if self.path.is_symlink() or info.st_mode & 0o077 or info.st_size>4096:raise ValueError('bounded private control file required')
            value=json.loads(self.path.read_bytes())
            if (not isinstance(value,dict) or set(value)!={'version','project','upstream','episode','paused','requested_at','changed_at'}
                    or type(value['version']) is not int or value['version']!=1 or value['project']!=self.project.fingerprint()
                    or value['upstream']!=UPSTREAM_COMMIT or type(value['paused']) is not bool
                    or not isinstance(value['episode'],str) or not re.fullmatch('[a-f0-9]{32}',value['episode'])
                    or any(type(value[key]) not in (float,int) or not math.isfinite(value[key]) or value[key]<=0
                           for key in ('requested_at','changed_at'))):
                raise ValueError('scoped operational control required')
            return {**value,'error':None}
        except FileNotFoundError:
            # Missing marker is the initial state; a broken symlink is not.
            if not self.path.is_symlink():return dict(paused=False,episode=None,error=None)
            return dict(paused=True,episode=None,error='InvalidControl')
        except (ValueError,TypeError,OSError,OverflowError):
            return dict(paused=True,episode=None,error='InvalidControl')

    def ensure(self):
        if self.read()['paused']:raise ActivityPaused('runtime pause requested; preserve work and release no new effects')

    def save(self,value):
        write_json(self.path,value)
        descriptor=os.open(self.root,os.O_RDONLY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)

    def pause(self):
        with self.lock():
            old=self.read()
            if old['error']:raise ValueError('invalid control must be diagnosed, not overwritten')
            if old['paused']:return old
            now=time.time()
            value=dict(version=1,project=self.project.fingerprint(),upstream=UPSTREAM_COMMIT,
                episode=uuid.uuid4().hex,paused=True,requested_at=now,changed_at=now)
            self.save(value)
            return self.read()

    def resume(self,episode):
        # Caller holds lock through quiescence/preflight checks and this write.
        old=self.read()
        if old['error'] or not old['paused'] or old['episode']!=episode:
            raise ValueError('exact current pause episode required')
        value={key:value for key,value in old.items() if key!='error'}
        self.save({**value,'paused':False,'changed_at':time.time()})
        return self.read()


def missing_profiles(project):
    from hermes_cli.profiles import profile_exists
    names=set(project.reviewers)
    for author in project.reviewers:names.update(project.reviewers_for(author))
    names.update((project.technical_roles or {}).values())
    names.update((project.coordination_roles or {}).values())
    names.update((project.delivery_roles or {}).values())
    return sorted(name for name in names if not profile_exists(name))


def doctor(project,root,store):
    errors=[]
    try:
        if not project.qualification and validation_files(project,store)[0] is None:errors.append('ValidationBundleRequired')
    except (ValueError,OSError,TypeError):errors.append('ValidationBundleInvalid')
    try:
        if shutil.disk_usage(root).free<1024**3:errors.append('LowDiskSpace')
    except OSError:errors.append('StorageUnavailable')
    try:
        Runner(project,store)  # Existing exact validator policy, no job or download.
        if project.browser_image and docker('image','inspect','--format','{{.Id}}',project.browser_image).strip()!=project.browser_image:
            raise ValueError('browser image missing')
    except (ValueError,OSError,subprocess.SubprocessError):errors.append('ValidationRuntimeUnavailable')
    if project.delivery_roles and not project.qualification:
        from .deployment import deployment_networks
        try:deployment_networks(project)
        except (ValueError,OSError,subprocess.SubprocessError,EffectBlocked):errors.append('DeploymentNetworksUnavailable')
    return dict(checked_at=time.time(),ready=not errors,errors=errors,missing_profiles=missing_profiles(project))
