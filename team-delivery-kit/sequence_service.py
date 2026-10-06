"""Launchd entrypoint: keep recoverable crashes restarting, respect terminal states."""
import os
from pathlib import Path
import sys

from dependent_sequence import load_plan, read_json
from sequence_supervisor import main as run_supervisor


def main():
    plan = load_plan(os.environ['DELIVERY_KIT_SEQUENCE_PLAN'])
    result = run_supervisor()
    from evalctl import PRIVATE
    ledger = read_json(PRIVATE / 'dependent-sequences' / (plan['name'] + '.json')) or {}
    if ledger.get('stage') in ('done', 'blocked'):
        # KeepAlive/SuccessfulExit=false must not spin on a terminal outcome.
        return 0
    return result or 1


if __name__ == '__main__':
    raise SystemExit(main())
