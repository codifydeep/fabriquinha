"""Offline Docker entrypoint: freeze baseline plus tests, before code edits."""
import json
import os
import sys
from pathlib import Path

from test_first_protocol import prepare_red,SnapshotRejection


def main():
    contract = json.loads((Path('/base') / 'contract.json').read_text())
    try:
        receipt = prepare_red('/base', '/workspace', '/snapshot', contract,
                              resume=os.environ.get('TEST_FIRST_RESUME') == '1')
    except SnapshotRejection as error:
        print(json.dumps(error.receipt,sort_keys=True),flush=True)
        sys.exit(1)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
