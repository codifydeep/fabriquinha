"""One evidence-bound resumption after reasoning-only output starvation."""
import hashlib
import json
import subprocess

from evalctl import PRIVATE, PROJECT
from controller_broker_image import installed_image
from portable_delivery import managed_handoff
from release_eval import save_receipt
from start_eval import cli, check_model_budget
from resume_browser_transport_fix import ISSUE, AUTHOR, IMAGE

SOURCE = '01a0f51a-5e99-7d89-928f-2b7ad41a1ec7'


def main(native_recovery=False, disabled=False):
    if disabled and native_recovery:
        raise ValueError('choose one verified correction')
    source_id = ('01a0f527-a505-784b-a776-21c120f6bbbc' if disabled else
                 '01a0f522-9be5-7020-a9d3-7257872837d0' if native_recovery else SOURCE)
    proxy_tag = '20260930.16' if disabled else '20260930.15' if native_recovery else '20260930.14'
    fix_id = ('controller-disabled-reasoning-v1' if disabled else
              'native-reasoning-off-recovery-v1' if native_recovery else 'controlled-low-reasoning-v1')
    effort = 'disabled' if disabled else 'low'
    if PROJECT != 'delivery-kit-port2' or installed_image(PROJECT) != IMAGE:
        raise ValueError('isolated installation identity mismatch')
    proxy = json.loads(subprocess.check_output(
        ['docker', 'inspect', PROJECT + '-model-proxy-1'], text=True))[0]
    env = proxy['Config']['Env']
    if (proxy['Config']['Image'] != 'delivery-kit-eval-model-proxy:' + proxy_tag
            or not proxy['State']['Running']
            or 'MODEL_PROXY_REASONING_EFFORT=' + effort not in env):
        raise ValueError('controlled reasoning fix not installed')
    marker = 'DELIVERY_HANDOFF ' + hashlib.sha256(
        (ISSUE + ':' + source_id + ':' + fix_id).encode()).hexdigest()
    wakeups = [w for w in cli('wakeup', 'list', ISSUE)
               if w.get('instruction', '').startswith(marker)]
    if len(wakeups) > 1:
        raise ValueError('duplicate reasoning fix wakeups')
    if wakeups:
        print(json.dumps({'stage': 'already_registered', 'wakeup_id': wakeups[0]['id']}))
        return
    runs = cli('runs', ISSUE)
    source = next((r for r in runs if r['id'] == source_id), None)
    if (not source or source.get('agent_id') != AUTHOR
            or source.get('status') != 'completed'
            or 'No visible answer was produced' not in (source.get('result') or {}).get('output', '')
            or any(r['status'] in ('running', 'queued') for r in runs)):
        raise ValueError('exact output-starvation evidence or idle state missing')
    managed = managed_handoff({'issue_id': ISSUE})
    if not managed or managed['state']['stage'] != 'test_first_blocked':
        raise ValueError('original blocked incident must remain preserved')
    budget = check_model_budget()
    instruction = (
        marker + '\nCONTROLLER VERIFIED MODEL CONFIGURATION CORRECTION. '
        'Prior task produced no visible output: four completions used all 8192 '
        'tokens for reasoning. Proxy now controls reasoning configuration; '
        'a real tool-call probe passed. ONE resumption of the same card, not '
        'permission to weaken acceptance. PHASE 1 TESTS ONLY. Write '
        'tests/test_browser_feedback_flow.py using the file tool. Do not edit '
        'product code or old tests. Implement the behavioral Node VM regression '
        'inside that unittest, according to the issue description. No root '
        'searches, ad-hoc node -e, /tmp writes or controller-file searches. '
        'Read only project files in /workspace. Run exactly: cd /workspace && '
        'PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -q 2>&1. '
        'Controller captures genuine Red independently. Preserve tests, frozen '
        'review, snapshots and the paid-call ceiling. Produce actual file-tool '
        'operations, not promises or simulated calls.')
    if native_recovery:
        instruction += (' The previous proxy incorrectly re-enabled reasoning '
                        'during Hermes native reasoning-off continuation. This '
                        'specific incompatibility is now fixed: enabled:false '
                        'is preserved and has passed a real tool-call probe. '
                        'No additional product scope or test exception is granted.')
    if disabled:
        instruction += (' Proxy now pins reasoning.enabled=false on EVERY request '
                        'for this isolated trial. Low-effort and native-off '
                        'transport recovery were ineffective in the real task. '
                        'Model remains unchanged; this distinct configuration '
                        'is not an identical retry. Execute the declared file '
                        'write and full suite; no narrative-only completion.')
    wakeup = cli('wakeup', 'create', ISSUE, '--agent-id', AUTHOR,
                 '--event', 'task.completed', '--task-id', source_id, '--mode', 'once',
                 '--instruction', instruction)
    receipt = {'issue_id': ISSUE, 'source_task': source_id,
               'proxy_image': proxy['Image'], 'reasoning_effort': effort,
               'wakeup_id': wakeup['id'], 'model_calls_before': budget['calls'],
               'stage': 'reasoning_fix_registered_not_approved'}
    save_receipt(PRIVATE / ('browser-disabled-reasoning-resume.json' if disabled else
                           'browser-native-reasoning-resume.json' if native_recovery
                           else 'browser-reasoning-resume.json'), receipt)
    cli('metadata', 'set', ISSUE, '--key', ('disabled_reasoning_fix_wakeup' if disabled else
                                         'native_reasoning_fix_wakeup' if native_recovery
                                         else 'reasoning_fix_wakeup'),
        '--value', wakeup['id'], '--type', 'string')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
