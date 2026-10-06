import json
import struct
import unittest
from unittest.mock import Mock, patch

from acp_wrapper import stream_prompt
from broker.acp_transport import Transport


class ACPStreamTests(unittest.TestCase):
    def test_wrapper_emits_update_before_reading_terminal_response(self):
        emitted = []
        update = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's'}}
        result = {'jsonrpc': '2.0', 'id': 7, 'result': {'stopReason': 'end_turn'}}
        class Response:
            reads = 0
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def readline(self, _):
                self.reads += 1
                if self.reads == 1:
                    return (json.dumps({'kind': 'notification', 'data': update}) + '\n').encode()
                if emitted != [update]:
                    raise AssertionError('update was buffered instead of forwarded')
                return (json.dumps({'kind': 'response', 'data': result}) + '\n').encode()
        with patch('acp_wrapper.urllib.request.urlopen', return_value=Response()):
            self.assertEqual(stream_prompt('http://broker', 'cap', {'id': 7}, emitted.append), result)

    def test_transport_calls_callback_before_terminal_frame(self):
        updates = []
        transport = Transport.__new__(Transport)
        transport.sock = Mock()
        transport.pending = b''
        transport.stderr_tail = b''
        transport.model_selected = True
        update = {'jsonrpc': '2.0', 'method': 'session/update', 'params': {'sessionId': 's'}}
        result = {'jsonrpc': '2.0', 'id': 7, 'result': {'stopReason': 'end_turn'}}
        payloads = [(json.dumps(value) + '\n').encode() for value in (update, result)]
        pieces = [bytes([1, 0, 0, 0]) + struct.pack('>I', len(data)) for data in payloads]
        frames = iter([pieces[0], payloads[0], pieces[1], payloads[1]])
        reads = 0
        def read(_, deadline=None):
            nonlocal reads
            reads += 1
            if reads == 3:
                self.assertEqual(updates, [update])
            return next(frames)
        transport.read_exact = read
        outcome = transport._exchange({'jsonrpc': '2.0', 'id': 7, 'method': 'session/prompt',
                'params': {'sessionId': 's', 'prompt': [{'type': 'text', 'text': 'test'}]}}, updates.append)
        self.assertEqual(outcome['_broker_notifications'], [update])

    def timed_transport(self, events):
        transport = Transport.__new__(Transport)
        transport.sock = Mock()
        transport.pending = b''
        transport.stderr_tail = b''
        transport.model_selected = True
        clock = [0]
        pieces = []
        for at, value in events:
            data = (json.dumps(value) + '\n').encode()
            pieces.extend([(at, bytes([1, 0, 0, 0]) + struct.pack('>I', len(data))), (at, data)])
        frames = iter(pieces)
        def read(_, deadline=None):
            at, data = next(frames)
            clock[0] = at
            if at >= deadline:
                raise TimeoutError('ACP reply deadline')
            return data
        transport.read_exact = read
        return transport, clock

    def prompt(self, transport):
        return transport._exchange({'jsonrpc': '2.0', 'id': 7, 'method': 'session/prompt',
            'params': {'sessionId': 's', 'prompt': [{'type': 'text', 'text': 'test'}]}})

    def test_active_prompt_can_exceed_five_minutes_without_resetting_total_cap(self):
        update = {'method': 'session/update', 'params': {'sessionId': 's'}}
        result = {'id': 7, 'result': {'stopReason': 'end_turn'}}
        transport, clock = self.timed_transport([(280, update), (560, update), (700, result)])
        with patch('broker.acp_transport.time.monotonic', side_effect=lambda: clock[0]):
            self.assertEqual(self.prompt(transport)['result'], result['result'])
        transport, clock = self.timed_transport([(at, update) for at in range(280, 1800, 280)] + [(1801, result)])
        with patch('broker.acp_transport.time.monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                self.prompt(transport)

    def test_silence_and_junk_do_not_extend_prompt_inactivity_window(self):
        for events in ([(301, {'id': 7, 'result': {}})],
                       [(280, {'unrecognized': 'noise'}), (301, {'id': 7, 'result': {}})]):
            transport, clock = self.timed_transport(events)
            with patch('broker.acp_transport.time.monotonic', side_effect=lambda: clock[0]):
                with self.assertRaises(TimeoutError):
                    self.prompt(transport)

    def test_partial_bytes_cannot_extend_absolute_read_deadline(self):
        transport = Transport.__new__(Transport)
        transport.sock = Mock()
        transport.sock.recv.return_value = b'x'
        with patch('broker.acp_transport.time.monotonic', side_effect=[299, 301]):
            with self.assertRaises(TimeoutError):
                transport.read_exact(8, 300)
        self.assertEqual(transport.sock.recv.call_count, 1)

    def test_missing_terminal_frame_is_an_error(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.readline.return_value = b''
        with patch('acp_wrapper.urllib.request.urlopen', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'without a terminal'):
                stream_prompt('http://broker', 'cap', {'id': 7}, lambda _: None)
