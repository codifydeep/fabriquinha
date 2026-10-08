"""Fixed, durable experiment before one independently sponsored author correction."""
import hashlib
import json
import time
import uuid

IMAGE='sha256:d10714bdd445427ccf5b3058aee1b7dbe7ed440f551aba078a495be3e8531344'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def validate(proof,config):
    if (proof.get('operation')!='fixed_indicator_write_hypothesis_v1' or proof.get('status')!='supported'
            or proof.get('original_manifest_sha256')!=config['manifest_sha256']
            or proof.get('original_test_sha256')!=config['diagnostic']['test_sha256']
            or proof.get('variant_manifest_sha256')==config['manifest_sha256']
            or proof.get('variant_test_sha256')==config['diagnostic']['test_sha256']
            or any(proof.get(k) is not True for k in ('inputs_unchanged','original_test_bodies_unchanged',
                'diagnostic_copy_only','fits_existing_file_limit'))
            or any(proof.get(k) is not False for k in ('valid_red_green_receipt','author_retry_authorized','delivery_approval'))
            or type(proof.get('variant_file_bytes')) is not int or not 0<proof['variant_file_bytes']<=32768):
        raise ValueError('exact nonapproving bounded indicator experiment required')
    try:import harness_qualification as jobs
    except ImportError:from broker import harness_qualification as jobs
    jobs.validate_result(proof['variant'],dict(manifest_sha256=proof['variant_manifest_sha256'],
        test_sha256={'tests/test_service_mode_indicator.py':proof['variant_test_sha256']}),require_timers=True)
    actual=proof.get('baseline_observation',{})
    if (actual.get('tests',0)<15 or actual.get('failures',0)<1 or any(actual.get(k)!=0 for k in
            ('errors','skipped','unexpected_successes','expected_failures'))):
        raise ValueError('separate executed failing baseline observation required')


def advance(b,config,state,effects,persist):
    if state.get('stage')!='plan_qualified' or not config.get('post_execution_diagnosis'):return state
    if any(state.get(role+'_decision',{}).get('action')!='request_test_revision' or not state.get(role+'_task')
           for role in ('cto','peer')):raise ValueError('two independent actual proposals required')
    record=state.get('indicator_experiment') or dict(stage='pending',approval=False)
    if record['stage']=='blocked' or record['stage']=='author_dispatched':return state
    def save(new):
        nonlocal state,record
        record=new;state={**state,'indicator_experiment':record};persist(state)
    if record['stage'] in ('pending','observing'):
        labels=(b.docker('GET','/volumes/'+config['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.test-first-task')!=config['source_task']:
            raise ValueError('owned frozen experiment input required')
        task=str(uuid.uuid5(uuid.NAMESPACE_URL,'indicator-write-hypothesis:'+config['source_task']+':'+config['manifest_sha256']))
        payload=dict(Image=IMAGE,User='10000:10000',Entrypoint=['python'],
            Cmd=['/service_mode_indicator_write_hypothesis.py','/delivery',config['manifest_sha256']],
            NetworkDisabled=True,Env=['PYTHONDONTWRITEBYTECODE=1'],
            Labels={'delivery-kit.purpose':'indicator-write-hypothesis','delivery-kit.source-task':config['source_task']},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=536870912,NanoCpus=1000000000,PidsLimit=96,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},
                Mounts=[dict(Type='volume',Source=config['volume'],Target='/delivery',ReadOnly=True)]))
        try:
            try:import test_first_job as jobs
            except ImportError:from broker import test_first_job as jobs
            with b.db() as con:result=jobs.run(b,con,task,'copy',payload)
        except TimeoutError:
            save(dict(stage='observing',experiment_task=task,approval=False));return state
        if result['exit_code']!=0:
            save(dict(stage='blocked',category='fixed_experiment_failed',experiment_task=task,
                output_sha256=result['output_sha256'],approval=False));return state
        proof=json.loads(result['output']);validate(proof,config)
        save(dict(stage='implementation_pending',experiment_task=task,proof=proof,proof_sha256=digest(proof),
            container_id=result['container_id'],output_sha256=result['output_sha256'],approval=False))
    if record['stage'] in ('implementation_pending','author_intent'):
        validate(record['proof'],config)
        if record['proof_sha256']!=digest(record['proof']):raise ValueError('durable experiment proof drift')
        if effects.remaining_calls()<config['minimum_calls'] or not effects.implementation_available(config['issue_id'],config['author']):return state
        first=record['stage']=='implementation_pending'
        if first:save({**record,'stage':'author_intent','intent_at':time.time()})
        note=('CONTROLLER EXPERIMENT-BACKED TESTS-ONLY CORRECTION. Independent CTO and Tech Lead sponsored '
            'indicator-write timer attribution. A fixed disposable-copy experiment passed all 15 positive tests '
            'and all 16 negative/background controls within 32768 bytes, preserving every assertion and product byte. '
            'Positive controls use a correct fixture, NOT the original app.js: the original product yielded 11 '
            'assertion failures in the diagnostic observation. That is not an approved Red receipt. '
            'Read the existing NEW test fully. Implement the bounded hypothesis yourself: instrument writes to '
            '#service-mode textContent and innerHTML, including equal-value writes, and classify callback timers '
            'when they fetch /service-mode OR write that indicator. Preserve board polling/debounce, all test '
            'methods/assertions, baseline files and every acceptance criterion. Do not subtract constants or '
            'whitelist source lines/delays. Change only the declared NEW test; save and inspect it, then finish. '
            'No product edit, copied diagnostic delivery, limit/depth/iteration reset, test skip or claimed approval. '
            'The controller must recapture full calibration and genuine full-suite Red on your frozen submission '
            'before independent test review and implementation. This is one changed-evidence execution. '
            'Experiment receipt SHA256: '+record['proof_sha256']+'\nDELIVERY_CONTROLLER_CALIBRATION_V1\n')
        marker=digest(dict(operation='experiment_backed_indicator_correction_v1',source=config['source_task'],
            proof=record['proof_sha256'],cto=state['cto_task'],peer=state['peer_task']))
        wake=effects.ensure_wakeup(config['issue_id'],config['author'],state['peer_task'],marker,note,allow_create=first)
        if wake:
            save({**record,'stage':'author_dispatched','wakeup':wake['id']})
            state={**state,'stage':'author_dispatched','author_wakeup':wake['id']};persist(state)
        elif time.time()-record['intent_at']>=1800:
            save({**record,'stage':'blocked','category':'author_intent_unobserved'})
    return state
