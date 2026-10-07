import unittest
from broker.acp_transport import validate_frame,ControllerPrompt
from execution_context import freeze


class ControllerPromptBoundsTests(unittest.TestCase):
    def frame(self,size):return dict(jsonrpc='2.0',id=1,method='session/prompt',params={'sessionId':'session','prompt':[{'type':'text','text':'x'*size}]})
    def test_actual_controller_capsule_can_carry_complete_bounded_context(self):
        capsule=freeze('brief','review')
        validate_frame(ControllerPrompt(self.frame(12175),capsule))
        validate_frame(ControllerPrompt(self.frame(32000),capsule))
    def test_json_client_or_marker_cannot_expand_default_bounds(self):
        import json
        capsule=freeze('brief','review');qualified=ControllerPrompt(self.frame(12175),capsule)
        for frame in (self.frame(12175),json.loads(json.dumps(qualified))):
            with self.assertRaises(ValueError):validate_frame(frame)
    def test_invalid_capsule_or_oversized_context_is_rejected(self):
        with self.assertRaises(ValueError):ControllerPrompt(self.frame(12175),{'sha256':'a'*64})
        with self.assertRaises(ValueError):validate_frame(ControllerPrompt(self.frame(32001),freeze('brief','review')))
