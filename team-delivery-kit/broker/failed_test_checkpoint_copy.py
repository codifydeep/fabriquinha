"""Fixed offline entrypoint: preserve failed candidate bytes in a new Red tree."""
import json
import os
import sys
from pre_red_snapshot_diagnostic import prepare_snapshot
from test_first_protocol import SnapshotRejection

if __name__ == '__main__':
    try:
        result = prepare_snapshot('/workspace', '/base', '/snapshot',
                                  resume=os.environ.get('TEST_FIRST_RESUME') == '1')
    except SnapshotRejection as error:
        print(json.dumps(error.receipt, sort_keys=True), flush=True)
        sys.exit(1)
    print(json.dumps(result, sort_keys=True), flush=True)
