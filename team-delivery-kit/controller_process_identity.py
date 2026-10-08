"""Recognize the host's own Python executable, including macOS app launchers."""
import os
from pathlib import Path
import subprocess
import sys


def interpreters():
    values={Path(sys.executable).resolve()}
    # CPython framework builds exec Python.app: argv[0] in ps is not
    # sys.executable. Query this exact live process, never accept a basename.
    actual=subprocess.check_output(['ps','-p',str(os.getpid()),'-o','comm='],text=True).strip()
    path=Path(actual)
    if path.is_absolute() and path.is_file():values.add(path.resolve())
    return values


def matches(command,script,label,allowed):
    suffix=' -u '+str(Path(script).resolve())+' --managed-label '+label
    if not command.endswith(suffix):return False
    prefix=command[:-len(suffix)]
    return bool(prefix) and Path(prefix).is_absolute() and Path(prefix).resolve() in allowed
