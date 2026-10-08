"""Fixed-model OpenRouter relay for the isolated evaluation; never logs payloads or keys."""
import http.client
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import threading
import tempfile
import time

from model_policy import MODEL, PLACEHOLDER_KEY
from decision_schema import apply as apply_decision_schema
from write_tool_schema import apply as apply_write_tool_schema
from test_artifact_schema import apply as apply_test_artifact_schema
from artifact_response_contract import metrics as artifact_metrics, validate as validate_artifact_response
import read_stream_recovery
import forced_tool_feedback
import deterministic_read_dispatch
import typed_decision_contract
import typed_test_source
import planning_schema
import proxy_request_rejections
from structured_response_contract import validate as validate_structured_response, StructuredResponseRejected

PLACEHOLDER = 'Bearer ' + PLACEHOLDER_KEY
MAX_BODY = 512 * 1024
MAX_RESPONSE = 4 * 1024 * 1024
RESPONSE_DEADLINE_SECONDS = 120
LOCK = threading.Lock()
COUNTER_PATH = os.environ.get('MODEL_PROXY_COUNTER_PATH')
PROVIDER_PAUSE = None


def provider_pause():
    if not COUNTER_PATH:
        return PROVIDER_PAUSE
    path = Path(COUNTER_PATH).with_name('provider-pause.json')
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 512:
        raise RuntimeError('unsafe provider pause receipt')
    value = json.loads(path.read_text())
    if (set(value) != {'category', 'upstream_status', 'call_number'}
            or value['category'] != 'upstream_payment_required'
            or value['upstream_status'] != 402
            or type(value['call_number']) is not int or value['call_number'] < 1):
        raise RuntimeError('invalid provider pause receipt')
    return value


def pause_provider(call_number):
    """Payment failure requires operator resolution, not another agent call."""
    global PROVIDER_PAUSE
    value = {'category': 'upstream_payment_required', 'upstream_status': 402,
             'call_number': call_number}
    with LOCK:
        if COUNTER_PATH:
            path = Path(COUNTER_PATH).with_name('provider-pause.json')
            fd, temporary = tempfile.mkstemp(prefix='.provider-pause-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(value, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
        PROVIDER_PAUSE = value
    return value


def load_calls():
    if not COUNTER_PATH:
        return 0  # unit-test and legacy mode only
    path = Path(COUNTER_PATH)
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('durable model counter missing')
    payload = json.loads(path.read_text())
    if set(payload) != {'calls'} or type(payload['calls']) is not int or payload['calls'] < 0:
        raise RuntimeError('invalid durable model counter')
    return payload['calls']


CALLS = load_calls()
MAX_CALLS = int(os.environ.get('MODEL_PROXY_MAX_CALLS', '4'))
MAX_OUTPUT_TOKENS = int(os.environ.get('MODEL_PROXY_MAX_OUTPUT_TOKENS', '2048'))
REASONING_EFFORT = os.environ.get('MODEL_PROXY_REASONING_EFFORT', '')
if REASONING_EFFORT not in ('', 'low', 'disabled'):
    raise ValueError('unsupported controlled reasoning effort')
if MAX_OUTPUT_TOKENS not in (2048, 4096, 8192):
    raise ValueError('unsupported model output budget')


def reserve_call():
    global CALLS
    with LOCK:
        if provider_pause():
            raise ValueError('upstream payment paused')
        if CALLS >= MAX_CALLS:
            raise ValueError('evaluation model-call limit reached')
        value = CALLS + 1
        if COUNTER_PATH:
            path = Path(COUNTER_PATH)
            fd, temporary = tempfile.mkstemp(prefix='.calls-', dir=path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump({'calls': value}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, path)
                directory = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
        CALLS = value
        return value


def validate_request(body):
    if not isinstance(body, dict) or body.get('model') != MODEL:
        raise ValueError('unapproved model')
    if not isinstance(body.get('messages'), list) or not body['messages']:
        raise ValueError('messages required')
    for field in ('max_tokens', 'max_completion_tokens'):
        if field in body and (type(body[field]) is not int or body[field] <= 0):
            raise ValueError('invalid output budget')
        if field in body:
            body[field] = min(body[field], MAX_OUTPUT_TOKENS)
    if 'max_tokens' not in body and 'max_completion_tokens' not in body:
        body['max_tokens'] = MAX_OUTPUT_TOKENS
    if body.get('stream') not in (None, False, True):
        raise ValueError('invalid stream flag')
    if REASONING_EFFORT:
        # Cap effort, but do not re-enable thinking when Hermes performs its
        # native reasoning-off recovery after a reasoning-only truncation.
        # This model declares reasoning non-mandatory. Use enabled:false rather
        # than an unsupported effort value; hiding reasoning does not save it.
        reasoning = body.get('reasoning')
        reasoning_off = (isinstance(reasoning, dict) and
                         (reasoning.get('enabled') is False or
                          reasoning.get('effort') == 'none')) or body.get('reasoning_effort') == 'none'
        body.pop('reasoning_effort', None)
        body.pop('include_reasoning', None)
        body['reasoning'] = ({'enabled': False}
                             if reasoning_off or REASONING_EFFORT == 'disabled'
                             else {'effort': REASONING_EFFORT})
    return typed_test_source.apply(typed_decision_contract.apply(apply_test_artifact_schema(apply_write_tool_schema(apply_decision_schema(body)))))


def safe_request_metrics(body):
    reasoning = body.get('reasoning')
    effort = reasoning.get('effort') if isinstance(reasoning, dict) else None
    if effort is None:
        effort = body.get('reasoning_effort')
    if isinstance(reasoning, dict) and reasoning.get('enabled') is False:
        effort = 'none'
    if effort not in ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'):
        effort = None
    fmt = body.get('response_format') or {}
    schema = fmt.get('json_schema') or {}
    return {**artifact_metrics(typed_test_source.validation_body(body)), 'output_limit': body.get('max_completion_tokens', body.get('max_tokens')),
            'reasoning_effort': effort,
            'structured_format': fmt.get('type') if fmt.get('type') in ('json_schema', 'json_object') else None,
            'decision_schema': schema.get('name') if schema.get('name') in (
                'delivery_decision_v1', 'delivery_qa_diagnosis_v1') else None,
            'strict_schema': schema.get('strict') is True,
            'require_parameters': (body.get('provider') or {}).get('require_parameters') is True,
            'tool_count': len(body.get('tools') or [])}


def safe_route_label(path):
    """Log only recognized fixed routes, never arbitrary paths or query strings."""
    known = {'/api/v1/chat/completions', '/api/v1/responses', '/api/v1/messages',
             '/api/v1/completions', '/v1/chat/completions', '/chat/completions',
             '/api/v1/api/v1/chat/completions'}
    return path if path in known else 'unrecognized_route'


def execution_route(path):
    match = re.fullmatch(r'/executions/([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})(/api/v1/chat/completions)', path)
    return (match[2], match[1]) if match else (path, None)


def safe_response_metrics(data, content_type):
    frames = (line[6:] for line in data.splitlines() if line.startswith(b'data: ')) \
        if content_type == 'text/event-stream' else (data,)
    result = {'finish_reason': None, 'completion_tokens': None, 'reasoning_tokens': None}
    for frame in frames:
        try:
            item = json.loads(frame)
        except (ValueError, TypeError):
            continue
        if not isinstance(item, dict):
            continue
        choices = item.get('choices')
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            finish = choices[0].get('finish_reason')
            if finish in ('stop', 'length', 'tool_calls', 'content_filter'):
                result['finish_reason'] = finish
        usage = item.get('usage')
        if isinstance(usage, dict):
            completion = usage.get('completion_tokens')
            details = usage.get('completion_tokens_details')
            reasoning = details.get('reasoning_tokens') if isinstance(details, dict) else None
            if type(completion) is int and completion >= 0:
                result['completion_tokens'] = completion
            if type(reasoning) is int and reasoning >= 0:
                result['reasoning_tokens'] = reasoning
    return result


def read_bounded_response(response, conn, deadline):
    """Bound total response time, not just idle time between streaming chunks."""
    chunks, size = [], 0
    while True:
        if getattr(response, 'isclosed', lambda: False)():
            return b''.join(chunks)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('model response deadline')
        # HTTPResponse owns the socket after Connection: close; conn.sock can
        # then be None even while the response reader is blocked.
        sock = conn.sock or getattr(getattr(response.fp, 'raw', None), '_sock', None)
        if sock is None:
            raise RuntimeError('model response socket unavailable')
        sock.settimeout(min(90, remaining))
        chunk = response.read1(min(65536, MAX_RESPONSE + 1 - size))
        if time.monotonic() >= deadline:
            raise TimeoutError('model response deadline')
        if not chunk:
            return b''.join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > MAX_RESPONSE:
            raise RuntimeError('model response too large')


def forward(body):
    key = Path('/secret/openrouter.key').read_text().strip()
    if not key or len(key) < 20:
        raise RuntimeError('model credential unavailable')
    conn = http.client.HTTPSConnection('openrouter.ai', timeout=90)
    deadline = time.monotonic() + RESPONSE_DEADLINE_SECONDS
    try:
        conn.request('POST', '/api/v1/chat/completions', json.dumps(body).encode(),
                     {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                      'HTTP-Referer': 'https://github.com/codifydeep/truco-online',
                      'X-Title': 'Team Delivery Kit isolated evaluation'})
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('model response deadline')
        if conn.sock:
            conn.sock.settimeout(min(90, remaining))
        response = conn.getresponse()
        data = read_bounded_response(response, conn, deadline)
        media_type = response.getheader('Content-Type', '')
        content_type = 'text/event-stream' if media_type.startswith('text/event-stream') else 'application/json'
        return response.status, data if response.status == 200 else b'{}', content_type
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path not in ('/status', '/provider-status', '/runtime-status'):
            self.send_error(404)
            return
        with LOCK:
            payload = ({'paused': bool(provider_pause()), 'incident': provider_pause()}
                       if self.path == '/provider-status' else
                       {'response_deadline_seconds': RESPONSE_DEADLINE_SECONDS,
                        'runtime_decision_contract': 'no-tools-json-v1'}
                       if self.path == '/runtime-status' else
                       {'calls': CALLS, 'max_calls': MAX_CALLS,
                        'remaining': max(0, MAX_CALLS - CALLS)})
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        status, data, content_type = 400, b'{}', 'application/json'
        reason = 'request_rejected'
        call_number = None
        request_metrics = {}
        response_metrics = {}
        recovery = None
        patch_feedback = None
        padding_receipt = None
        stage, request_sha, local_rejection = 'admission', None, None
        route, execution_id = execution_route(self.path)
        started = time.monotonic()
        started_at = time.time()
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if route != '/api/v1/chat/completions':
                raise ValueError('unapproved path')
            if self.headers.get('Authorization') != PLACEHOLDER:
                raise ValueError('unapproved authorization')
            if not 0 < size <= MAX_BODY:
                raise ValueError('request body size limit')
            stage = 'decode'
            raw_request = self.rfile.read(size)
            request_sha = hashlib.sha256(raw_request).hexdigest()
            incoming = json.loads(raw_request)
            requested_stream = incoming.get('stream') is True
            stage = 'contract'
            body = validate_request(incoming)
            stage = 'metrics'
            request_metrics = safe_request_metrics(body)
            stage = 'read_dispatch'
            dispatch=deterministic_read_dispatch.make(body,execution_id)
            if dispatch:
                stage = 'read_validation'
                validate_artifact_response(body,dispatch['data'],dispatch['media_type'])
                stage = 'read_ledger'
                deterministic_read_dispatch.record(COUNTER_PATH,dispatch)
                status,data,content_type=200,dispatch['data'],dispatch['media_type']
                reason='controller_read_dispatch'
                response_metrics['read_request_provenance']='controller_request_not_read_evidence'
            else:
                stage = 'preflight'
                typed_decision_contract.length_feedback_preflight(COUNTER_PATH,execution_id,body)
                typed_decision_contract.format_feedback_preflight(COUNTER_PATH,execution_id,body)
                scope=read_stream_recovery.identity(body,execution_id)
                read_stream_recovery.preflight(COUNTER_PATH,scope)
                patch_scope=forced_tool_feedback.identity(body,execution_id)
                forced_tool_feedback.preflight(COUNTER_PATH,patch_scope)
            for attempt in range(0 if dispatch else 2):
                stage = 'upstream'
                call_number = reserve_call()  # every attempt persists before network side effect
                if recovery:read_stream_recovery.retry_reserved(COUNTER_PATH,recovery,call_number)
                if patch_feedback:forced_tool_feedback.retry_reserved(COUNTER_PATH,patch_feedback,call_number)
                status, data, content_type = forward(body)
                if status == 402:pause_provider(call_number)
                reason = 'upstream_response'
                if status == 200:
                    stage = 'response'
                    response_metrics = safe_response_metrics(data, content_type)
                    data,content_type=typed_test_source.translate(body,data,content_type)
                    padding_receipt=None
                    if os.environ.get('MODEL_PROXY_TECHNICAL_PADDING')=='1':
                        data,padding_receipt=typed_decision_contract.normalize_technical_padding(body,data,content_type)
                    if os.environ.get('MODEL_PROXY_REVIEW_PADDING')=='1':
                        data,review_padding=typed_decision_contract.normalize_review_padding(body,data,content_type)
                        if review_padding:padding_receipt=review_padding
                        data,evidence_padding=typed_decision_contract.normalize_evidence_padding(body,data,content_type)
                        if evidence_padding:padding_receipt=evidence_padding
                        data,validation_padding=typed_decision_contract.normalize_validation_padding(body,data,content_type)
                        if validation_padding:padding_receipt=validation_padding
                    try:
                        data,content_type,typed_receipt=typed_decision_contract.translate(body,data,content_type)
                    except StructuredResponseRejected as error:
                        revised=None
                        if attempt==0 and getattr(error,'length_feedback',None):
                            typed_decision_contract.record(COUNTER_PATH,execution_id,error.receipt)
                            revised=typed_decision_contract.claim_length_feedback(COUNTER_PATH,execution_id,error,body,call_number)
                        if attempt==0 and revised is None:
                            revised=typed_decision_contract.claim_format_feedback(COUNTER_PATH,execution_id,error,body,call_number)
                            if revised is not None:
                                typed_decision_contract.record(COUNTER_PATH,execution_id,error.receipt)
                        if revised is None:raise
                        print(json.dumps({'event':'model_proxy_bounded_decision_feedback','execution_id':execution_id,
                            'first_call':call_number,'rejected_upstream_sha256':error.receipt['upstream_sha256'],
                            'attempt_limit':1,'worker_tool_executed':False,'response_forwarded':False}),flush=True)
                        body=revised
                        continue
                    if typed_receipt:
                        if padding_receipt:typed_receipt['transport_padding']=padding_receipt
                        typed_decision_contract.record(COUNTER_PATH,execution_id,typed_receipt)
                        response_metrics['decision_adapter']='validated_typed_decision_adapter_v1'
                        response_metrics['decision_upstream_sha256']=typed_receipt['upstream_sha256']
                        response_metrics['decision_arguments_sha256']=typed_receipt['arguments_sha256']
                        response_metrics['decision_output_sha256']=typed_receipt['output_sha256']
                    validate_structured_response(body,data,content_type)
                    try:validate_artifact_response(typed_test_source.validation_body(body), data, content_type)
                    except ValueError as error:
                        if attempt==0:
                            revised=forced_tool_feedback.claim(COUNTER_PATH,patch_scope,error,body,call_number)
                            if revised is not None:
                                patch_feedback=patch_scope
                                print(json.dumps(dict(event='model_proxy_forced_tool_feedback',execution_id=execution_id,
                                    tool=forced_tool_feedback.metrics(body)['artifact_selected_tool'],
                                    first_call=call_number,attempt_limit=1,worker_tool_executed=False,
                                    response_forwarded=False)),flush=True)
                                body=revised
                                continue
                            recovery=read_stream_recovery.claim(COUNTER_PATH,scope,call_number,
                                getattr(error,'category',None),content_type)
                            if recovery:
                                print(json.dumps({'event':'model_proxy_read_recovery','stage':'claimed',
                                    'execution_id':execution_id,'first_call':call_number,
                                    'scope_sha256':scope['scope'],'category':'upstream_stream_error',
                                    'retry_limit':1,'response_forwarded':False}),flush=True)
                                continue
                        raise
                if status==200:
                    data,content_type=typed_test_source.caller_response(body,data,content_type,requested_stream)
                    data,content_type=planning_schema.caller_response(body,data,content_type,requested_stream)
                if recovery:
                    read_stream_recovery.finish(COUNTER_PATH,recovery,status==200,
                        'validated_read' if status==200 else 'upstream_status')
                    response_metrics['read_stream_recovered']=status==200
                    recovery=None
                if patch_feedback:
                    forced_tool_feedback.finish(COUNTER_PATH,patch_feedback,status==200)
                    response_metrics['forced_tool_feedback_passed']=status==200
                    patch_feedback=None
                break
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            if execution_id and request_sha and call_number is None:
                local_rejection = proxy_request_rejections.describe(error,stage,execution_id,request_sha)
            status = 400
            reason = str(error) if str(error) in (
                'unapproved model', 'messages required', 'invalid output budget',
                'invalid stream flag', 'evaluation model-call limit reached',
                'unapproved request', 'unapproved path', 'unapproved authorization',
                'request body size limit', 'review inspection stalled', 'artifact tool response invalid',
                'typed surgical tool missing from actual registry',
                'read stream recovery exhausted') else 'invalid_request'
            if reason == 'artifact tool response invalid':
                response_metrics['artifact_rejection_category'] = getattr(error, 'category', 'unknown')
                if getattr(error,'diagnostic',None):
                    response_metrics['artifact_rejection_diagnostic']=error.diagnostic
                response_metrics['artifact_output_budget_reached'] = (
                    type(response_metrics.get('completion_tokens')) is int
                    and response_metrics['completion_tokens'] >= body['max_tokens'])
                status = 502
                content_type = 'application/json'
                data = b'{"error":{"code":"artifact_tool_response_invalid"}}'
            if reason == 'review inspection stalled':
                data = b'{"error":{"code":"review_inspection_stalled"}}'
            if isinstance(error,StructuredResponseRejected):
                status,reason,content_type=502,'structured_decision_response_invalid','application/json'
                response_metrics['structured_rejection_category']=error.category
                if error.diagnostic:
                    response_metrics['structured_rejection_diagnostic']=error.diagnostic
                data=b'{"error":{"code":"structured_decision_response_invalid"}}'
                rejection=getattr(error,'receipt',None)
                if rejection:
                    if padding_receipt:rejection['transport_padding']=padding_receipt
                    try:
                        typed_decision_contract.record(COUNTER_PATH,execution_id,rejection)
                        response_metrics['decision_upstream_sha256']=rejection['upstream_sha256']
                        response_metrics['decision_rejection_persisted']=True
                    except Exception:
                        status,reason=503,'typed_rejection_receipt_unavailable'
                        data=b'{"error":{"code":"typed_rejection_receipt_unavailable"}}'
            if reason == 'evaluation model-call limit reached':
                data = b'{"error":{"code":"evaluation_model_call_limit"}}'
            if str(error) == 'upstream payment paused':
                status, reason = 402, 'upstream_payment_paused'
                data = b'{"error":{"code":"upstream_payment_paused"}}'
        except Exception as error:
            if execution_id and request_sha and call_number is None:
                local_rejection = proxy_request_rejections.describe(error,stage,execution_id,request_sha)
            status = 503  # never return upstream bodies or local exception text
            reason = type(error).__name__
        finally:
            if patch_feedback:
                try:forced_tool_feedback.finish(COUNTER_PATH,patch_feedback,False)
                except Exception:
                    status,reason,data,content_type=503,'patch_feedback_receipt_unavailable',b'{}','application/json'
            if recovery:
                try:
                    read_stream_recovery.finish(COUNTER_PATH,recovery,False,
                        'upstream_stream_error' if response_metrics.get('artifact_rejection_category')=='upstream_stream_error'
                        else 'interrupted')
                except Exception:
                    status,reason,data,content_type=503,'read_recovery_receipt_unavailable',b'{}','application/json'
        event={'event': 'model_proxy_request', 'status': status,
                          'category': reason, 'call_number': call_number,
                          'route': safe_route_label(route), 'execution_id': execution_id,
                          'started_at': started_at,
                          'duration_seconds': round(time.monotonic() - started, 3),
                          'response_deadline_seconds': RESPONSE_DEADLINE_SECONDS,
                          **request_metrics, **response_metrics}
        if local_rejection:
            try:
                proxy_request_rejections.record(COUNTER_PATH,local_rejection)
                event['local_rejection'] = local_rejection
            except Exception:
                status=503
                event.update(status=status,category='request_rejection_receipt_unavailable')
                data=b'{"error":{"code":"request_rejection_receipt_unavailable"}}'
                content_type='application/json'
        if event.get('artifact_rejection_category'):
            try:
                import artifact_rejection_receipts
                artifact_rejection_receipts.record(COUNTER_PATH,event)
            except Exception:
                status=503
                event.update(status=status,category='artifact_rejection_receipt_unavailable')
                data=b'{"error":{"code":"artifact_rejection_receipt_unavailable"}}'
                content_type='application/json'
        print(json.dumps(event), flush=True)
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
