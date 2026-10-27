"""Reserve the two owned Docker networks before enabling a real delivery trial.

Run only on a paused, drained installation. Unknown create acknowledgements are
observed through the existing effect journal; never resent, pruned or reset.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.deployment import prepare_networks,network_identity
from fabriquinha.config import pool_subnets
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime


def prepare(root,upstream):
    runtime=Runtime(Path(root).absolute(),Path(upstream).absolute())
    if runtime.project.qualification or not runtime.project.delivery_roles:
        raise ValueError('explicit real delivery installation required')
    with runtime.control.lock():
        if not runtime.control.read()['paused']:raise ValueError('pause installation before provisioning')
        _,kbc,_=native()
        with kbc.connect_closing() as conn:
            status=runtime.pause_status(conn)
            if not status['agents_stopped']:raise ValueError('settle workers before provisioning')
        expected=[network_identity(runtime.project,suffix) for suffix in ('default','qa')]
        for key in status['pending_effects']:
            effect=json.loads((runtime.store.root/'effects'/(key+'.json')).read_bytes())
            if effect.get('identity') not in expected:
                raise ValueError('settle unrelated effects before provisioning')
        # The same network creation may be pending. Reconcile by observation,
        # never by a second create; do not deadlock behind its own intent.
        networks=prepare_networks(runtime.project,runtime.store)
        result=dict(project=runtime.project.fingerprint(),networks=networks,model_calls=0,delivery_approval=False)
        result.update(network_pool=runtime.project.network_pool,core_subnet=pool_subnets(runtime.project.network_pool).get('core'))
        write_json(runtime.root/'deployment-network-preflight.json',result)
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.root,args.upstream),indent=2))
