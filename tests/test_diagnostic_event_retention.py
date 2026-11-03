import json
import unittest
from fabriquinha.executor import validation_output

class Retention(unittest.TestCase):
    def test_polling_does_not_evict_error(self):
        events=[{'event':'http_error','status':404,'path':'/api/rooms/old'}]+[{'event':'room_response','status':200} for _ in range(600)]
        output='\n'.join('FABRIQUINHA_PROGRESS '+json.dumps(e) for e in events)+'\n'+json.dumps({'failures':[]})
        report,kept=validation_output(output)
        self.assertEqual(report,{'failures':[]})
        self.assertEqual(len(kept),256)
        self.assertEqual(kept[0],events[0])
    def test_error_storm_is_bounded(self):
        events=[{'event':'http_error','status':409,'sequence':i} for i in range(1000)]
        _,kept=validation_output('\n'.join('FABRIQUINHA_PROGRESS '+json.dumps(e) for e in events))
        self.assertEqual(len(kept),256)
        self.assertEqual(kept[-1]['sequence'],999)
