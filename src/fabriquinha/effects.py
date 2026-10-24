"""One small journal for uncertain external effects, not a second task lifecycle."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time
from .artifacts import digest, encoded


class Pending(RuntimeError):
    pass


class EffectBlocked(RuntimeError):
    pass


class NotSent(RuntimeError):
    """Trusted pre-effect fence ONLY: no external mutation has been attempted."""


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class Journal:
    def __init__(self, root, *, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.clock = clock

    @contextmanager
    def lock(self, key):
        with (self.root / (digest(key) + '.lock')).open('a') as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            yield

    def do(self, key, identity, send, observe, *, timeout=120):
        path = self.root / (digest(key) + '.json')
        with self.lock(key):
            first = not path.exists()
            if first:
                state = dict(identity=identity, state='intent', started=self.clock(), deadline=self.clock()+timeout)
                write_json(path, state)
            else:
                state = json.loads(path.read_bytes())
                if state['identity'] != identity:
                    raise ValueError('effect key reused with another identity')
                if state['state'] == 'done':
                    return state['result']
                if state['state']=='not_sent':
                    # Start the observation clock at the first actual attempt,
                    # never refresh an uncertain/already-sent effect's deadline.
                    first=True
                    state.update(state='intent',started=self.clock(),deadline=self.clock()+timeout)
                    write_json(path,state)
            try:
                result = send() if first else observe()
            except NotSent:
                if not first:raise  # An interrupted observer cannot unsend an earlier mutation.
                state.update(state='not_sent',last_error='PreEffectFence')
                write_json(path,state)
                raise
            except EffectBlocked as error:
                state.update(state='blocked', last_error=str(error)[:2000])
                write_json(path, state)
                raise
            except Exception as error:
                state['last_error'] = type(error).__name__
                result = None
            if result is not None:
                state.update(state='done', result=result)
                write_json(path, state)
                return result
            write_json(path, state)
            if self.clock() >= state['deadline']:
                raise EffectBlocked('effect remains unobserved: ' + str(key))
            raise Pending('observe the original effect: ' + str(key))
