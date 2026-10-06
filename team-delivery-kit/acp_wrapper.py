"""Restricted stdio ACP wrapper. Requires a controller-issued capability, never a PAT."""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from model_policy import MODEL

URL = 'http://execution-broker:8090'


def stream_prompt(call_url, capability, frame, output):
    """Forward actual ACP notifications before the final prompt response."""
    request = urllib.request.Request(call_url + '/v1/acp-message-stream',
        data=json.dumps({'frame': frame}).encode(),
        headers={'Authorization': 'Bearer ' + capability, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=330) as response:
        while True:
            line = response.readline(1024 * 1024 + 1)
            if not line:
                raise RuntimeError('prompt stream ended without a terminal response')
            if len(line) > 1024 * 1024:
                raise RuntimeError('prompt stream frame too large')
            event = json.loads(line)
            if event.get('kind') == 'notification':
                notification = event['data']
                if notification.get('method') != 'session/update' or 'id' in notification:
                    raise ValueError('invalid streamed notification')
                output(notification)
            elif event.get('kind') == 'response':
                return event['data']
            elif event.get('kind') == 'error':
                return {'jsonrpc': '2.0', 'id': frame['id'], 'error': {
                    'code': -32000, 'message': 'restricted broker stream failed: '
                    + str(event['data'].get('category', 'unknown'))}}
            else:
                raise ValueError('invalid prompt stream event')


def main():
    if '--version' in sys.argv:
        print('hermes-isolated 0.21.0')
        return
    if '--check' in sys.argv:
        print('Restricted ACP wrapper installed; execution requires controller authorization')
        return
    capability = os.environ.get('DELIVERY_EXECUTION_CAPABILITY', '')
    if not capability:
        # This wrapper is trusted controller code, never mounted in the worker.
        identity = {'task_id': os.environ['MULTICA_TASK_ID'], 'agent_id': os.environ['MULTICA_AGENT_ID']}
        request = urllib.request.Request(URL + '/v1/native-grants', data=json.dumps(identity).encode(),
            headers={'Authorization': 'Bearer ' + Path('/eval-state/broker-controller-token').read_text(),
                     'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=15) as response:
            capability = json.load(response)['capability']
    if not capability or len(capability) != 64:
        raise RuntimeError('controller-issued execution capability required')
    def call(path, payload, timeout=40):
        request = urllib.request.Request(URL + path, data=json.dumps(payload).encode(),
            headers={'Authorization': 'Bearer ' + capability, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    opened = call('/v1/acp-open', {})
    try:
        for line in sys.stdin:
            frame = {}
            try:
                if len(line) > 16384:
                    raise ValueError('ACP request size limit')
                frame = json.loads(line)
                if frame.get('method') not in ('initialize', 'session/new', 'session/resume',
                                               'session/set_model', 'session/prompt'):
                    if 'id' in frame:
                        print(json.dumps({'jsonrpc': '2.0', 'id': frame['id'], 'error': {
                            'code': -32601, 'message': 'Method not qualified'}}), flush=True)
                    continue
                resume = frame.get('method') == 'session/new' and opened.get('resume_session_id')
                if resume:
                    frame = {**frame, 'method': 'session/resume', 'params': {'sessionId': resume}}
                # Streaming reads allow 330 seconds of silence, outliving the
                # broker's 300-second inactivity window. The broker separately
                # caps total prompt duration; updates do not remove that cap.
                result = (stream_prompt(URL, capability, frame,
                                        lambda notification: print(json.dumps(notification), flush=True))
                          if frame['method'] == 'session/prompt'
                          else call('/v1/acp-message', {'frame': frame}, timeout=40))
                for notification in result.pop('_broker_notifications', []):
                    print(json.dumps(notification), flush=True)
                if resume and 'result' in result and 'error' not in result:
                    # A resumed transport starts with no selected-model proof. Pin it
                    # before Multica can skip a redundant set_model and send a prompt.
                    model_result = call('/v1/acp-message', {'frame': {
                        'jsonrpc': '2.0', 'id': str(frame['id']) + ':model',
                        'method': 'session/set_model',
                        'params': {'sessionId': resume,
                                   'modelId': MODEL}}})
                    for notification in model_result.pop('_broker_notifications', []):
                        print(json.dumps(notification), flush=True)
                    if 'error' in model_result:
                        result = {'jsonrpc': '2.0', 'id': frame['id'], 'error': model_result['error']}
                    else:
                        result['result']['sessionId'] = resume
                        result['result']['_meta'] = {'delivery-kit': {'resumedPersistedSession': True}}
                print(json.dumps(result), flush=True)
            except Exception as error:
                category = ('http_' + str(error.code) if isinstance(error, urllib.error.HTTPError)
                            else type(error).__name__)
                print('ACP wrapper request failed: ' + category, file=sys.stderr, flush=True)
                if 'id' in frame:
                    print(json.dumps({'jsonrpc': '2.0', 'id': frame['id'], 'error': {
                        'code': -32000, 'message': 'restricted broker operation failed: ' + category}}),
                        flush=True)
    finally:
        try:
            call('/v1/acp-close', {})
        except Exception:
            print('ACP close not acknowledged; lease reconciliation required', file=sys.stderr)


if __name__ == '__main__':
    main()
