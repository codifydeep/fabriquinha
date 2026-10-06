"""Operator CLI for generic frozen-delivery and exact-SHA deployment gates."""
import argparse
import json

from portable_contract import load
from portable_preflight import verify
from portable_qualification import run_frozen_tests, verify_docker_deployment


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--contract', required=True)
    actions = parser.add_subparsers(dest='action', required=True)
    frozen = actions.add_parser('frozen')
    frozen.add_argument('--repo', required=True)
    frozen.add_argument('--base-sha', required=True)
    frozen.add_argument('--snapshot', required=True)
    deployed = actions.add_parser('deployed')
    deployed.add_argument('--container', required=True)
    deployed.add_argument('--url', required=True)
    deployed.add_argument('--source-sha', required=True)
    args = parser.parse_args()
    contract = load(args.contract)
    if args.action == 'frozen':
        before = verify(args.repo, args.base_sha, args.snapshot, contract)
        tests = run_frozen_tests(args.snapshot, contract)
        after = verify(args.repo, args.base_sha, args.snapshot, contract)
        if before != after:
            raise ValueError('frozen delivery changed during validation')
        result = {'preflight': before, 'tests': tests}
    else:
        result = verify_docker_deployment(args.container, args.url,
                                          args.source_sha, contract)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
