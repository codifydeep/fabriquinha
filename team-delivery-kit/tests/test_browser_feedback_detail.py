import unittest
import ast
import inspect
from types import SimpleNamespace
from browser_feedback_detail import exact_json, observe_detail_api, run, ORIGIN, ExpectedDetailFailure


def response(status, body, mime='application/json'):
    return SimpleNamespace(status=status, headers={'content-type': mime}, json=lambda: body)


class DetailApiRecipeTests(unittest.TestCase):
    def test_detail_sort_uses_visible_label_not_nonexistent_option_value(self):
        from browser_feedback_detail import observe_detail_ui
        calls = [node for node in ast.walk(ast.parse(inspect.getsource(observe_detail_ui)))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'select_option']
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args, [])
        self.assertEqual([(arg.arg, ast.literal_eval(arg.value)) for arg in calls[0].keywords],
                         [('label', 'Oldest first')])

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
            def __init__(self):
                self.calls=[]; self.completed=False
            def post(self,url,data=None):
                if url.endswith('/complete'):
                    self.completed=True
                    return response(200,{'id':1})
                self.title=data['title']
                self.completed=False
                return response(201,{'id': 1, 'title': self.title, 'completed': False})
            def get(self,url):
                self.calls.append(url)
                path=url.removeprefix(ORIGIN).split('?',1)[0]
                if path=='/feedback':return response(200,{'items': []})
                if path=='/feedback/summary':return response(200,{'total': 1, 'open': 1, 'completed': 0})
                if path=='/feedback/1':return response(200,{'item': {'id':1,'title':self.title,'completed':self.completed}})
                if path=='/feedback/2147483647':return response(404,{'error':'Feedback not found'})
                return response(400,{'error':'Invalid feedback id'})
        fixture=Fixture()
        self.assertEqual(len(observe_detail_api(fixture)),7)
        self.assertIn(ORIGIN+'/feedback/1?ignored=1',fixture.calls)
        original=fixture.get
        fixture.get=lambda url: response(200,{'error':'Feedback not found'}) if url.endswith('/2147483647') else original(url)
        with self.assertRaises(AssertionError):observe_detail_api(fixture)

    def test_only_exact_driver_injected_console_failure_is_allowed_once(self):
        guard=ExpectedDetailFailure(); a=object(); b=object(); errors=[]
        url=ORIGIN+'/feedback/1'
        message=SimpleNamespace(type='error',text=guard.MESSAGE,location={'url':url})
        guard.injected(a,url)
        guard.console(b,message,errors)
        self.assertEqual(len(errors),1)
        guard.console(a,message,errors)
        self.assertEqual(len(errors),1)
        guard.console(a,message,errors)
        self.assertEqual(len(errors),2)
        with self.assertRaises(AssertionError):guard.injected(a,ORIGIN+'/feedback')

    def test_arbitrary_commands_are_not_enabled(self):
        for scenario in ('shell','../script.py'):
            with self.assertRaisesRegex(ValueError,'not qualified'):run(scenario)

    def test_unexpected_console_errors_retain_only_fixture_location(self):
        guard = ExpectedDetailFailure(); errors = []; page = object()
        message = SimpleNamespace(type='error', text='HTTP 400',
                                  location={'url': ORIGIN + '/feedback?status=open'})
        guard.console(page, message, errors)
        self.assertEqual(errors, ['HTTP 400 at ' + ORIGIN + '/feedback?status=open'])
        message.location = {'url': 'https://unrelated.invalid/private'}
        guard.console(page, message, errors)
        self.assertEqual(errors[-1], 'HTTP 400 at unknown')
