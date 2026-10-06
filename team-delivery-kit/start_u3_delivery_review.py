"""Operator admission bridge: verifies GitHub binding before native review dispatch."""
import json
import argparse
import tempfile
from pathlib import Path

import publish_u3_coverage as publication
import integrate_u3_predecessors as gates
from broker import u3_delivery_review as review


def main(*, resume_infrastructure=False, resume_reads=False):
    if resume_infrastructure and resume_reads:raise ValueError('one recovery cause required')
    if publication.RECEIPT.is_symlink():
        raise ValueError('regular coverage publication receipt required')
    published = json.loads(publication.RECEIPT.read_text())
    bundle = publication.load_bundle()
    publication.validate_bundle(bundle)
    base, binding = publication.publication_base(bundle)
    if (published.get('stage') != 'pr_open' or published['pr_number'] != 36
            or published['head_sha'] != review.HEAD or published['base_sha'] != review.BASE
            or base != review.BASE or published['git_binding'] != binding
            or published['manifest_sha256'] != bundle['contract']['manifest_sha256']
            or published['review_receipt_sha256'] != publication.digest(bundle['receipt'])):
        raise ValueError('exact published coverage lineage required')
    pr = gates.api('pulls/36')
    if (pr.get('state') != 'open' or pr.get('merged')
            or pr['head']['sha'] != review.HEAD or pr['head']['ref'] != publication.BRANCH
            or pr['base']['sha'] != base or pr['base']['ref'] != 'main'
            or any(pr[k]['repo']['full_name'] != publication.REPOSITORY for k in ('head','base'))):
        raise ValueError('exact unmerged same-repository coverage PR required')
    gates.protection_ok(gates.api('branches/main/protection'))
    gates.exact_ci(gates.api('commits/' + review.HEAD + '/check-runs'), review.HEAD)
    with tempfile.TemporaryDirectory(prefix='u3-final-review-admission-') as tmp:
        snapshot = Path(tmp)
        publication.export_snapshot(bundle, snapshot)
        content = publication.preflight(publication.REPO, bundle, snapshot, target_base=base)
        publication.verify_commit(publication.REPO, review.HEAD, base, content)
    operation='resume_reads' if resume_reads else ('resume_infrastructure' if resume_infrastructure else 'begin')
    script = 'import broker as b,json,u3_delivery_review as r; print(json.dumps(r.'+operation+'(b)))'
    print(publication.run('docker','exec','-e','PYTHONPATH=/',publication.PROJECT+'-execution-broker-1',
                          'python','-c',script).decode().strip())


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--resume-infrastructure',action='store_true')
    parser.add_argument('--resume-reads',action='store_true')
    args=parser.parse_args()
    main(resume_infrastructure=args.resume_infrastructure,resume_reads=args.resume_reads)
