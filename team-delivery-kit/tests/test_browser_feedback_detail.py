import unittest
from types import SimpleNamespace
from browser_feedback_detail import exact_json, observe_detail_api, run, ORIGIN


def response(status, body, mime='application/json'):
    return SimpleNamespace(status=status, headers={'content-type': mime}, json=lambda: body)


class DetailApiRecipeTests(unittest.TestCase):
    def test_http_mime_shape_and_json_types_cannot_be_weakened(self):
        expected={'item': {'id': 1, 'title': 'literal', 'completed': False}}
        self.assertEqual(exact_json(response(200, expected),200,expected), expected)
        for candidate in (response(201,expected),response(200,expected,'text/html'),
                          response(200,{**expected,'extra': True}),
                          response(200,{'item': {**expected['item'],'id': True}}),
                          response(200,{'item': {**expected['item'],'completed': 0}})):
            with self.assertRaises(AssertionError): exact_json(candidate,200,expected)

    def test_api_driver_requires_real_negative_statuses_and_read_only_behavior(self):
        class Fixture:
            calls=[]
            def post(self,url,data):
                self.title=data['title']
                return response(201,{'id': 1, 'title': self.title, 'completed': False})
            def get(self,url):
                self.calls.append(url)
                path=url.removeprefix(ORIGIN).split('?',1)[0]
                if path=='/feedback':return response(200,{'items': []})
                if path=='/feedback/summary':return response(200,{'total': 1, 'open': 1, 'completed': 0})
                if path=='/feedback/1':return response(200,{'item': {'id':1,'title':self.title,'completed':False}})
                if path=='/feedback/2147483647':return response(404,{'error':'Feedback not found'})
                return response(400,{'error':'Invalid feedback id'})
        fixture=Fixture()
        self.assertEqual(len(observe_detail_api(fixture)),6)
        self.assertIn(ORIGIN+'/feedback/1?ignored=1',fixture.calls)
        original=fixture.get
        fixture.get=lambda url: response(200,{'error':'Feedback not found'}) if url.endswith('/2147483647') else original(url)
        with self.assertRaises(AssertionError):observe_detail_api(fixture)

    def test_ui_and_arbitrary_commands_are_not_enabled_by_draft(self):
        for scenario in ('feedback-board-detail-ui-v1','shell','../script.py'):
            with self.assertRaisesRegex(ValueError,'not qualified'):run(scenario)
