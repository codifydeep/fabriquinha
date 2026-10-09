import ast
import inspect
import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from browser_feedback_latest import ConsoleGuard, ERRORS, ORIGIN, exact, observe_api, observe_ui, run
from browser_qa_recipes import recipe_for


def response(status, value, mime='application/json'):
    return SimpleNamespace(status=status, headers={'content-type': mime}, json=lambda: value)


class Fixture:
    def __init__(self):
        self.items=[];self.calls=[];self.mutate=False

    def post(self,url,data=None):
        if url.endswith('/complete'):
            self.items[0]['completed']=True
            return response(200,{})
        item={'id':len(self.items)+1,'title':data['title'],'completed':False}
        self.items.append(item)
        return response(201,dict(item))

    def get(self,url):
        self.calls.append(url)
        if urlsplit(url).path!='/feedback/latest':
            return response(200,{'items':[dict(item) for item in self.items]})
        query=parse_qs(urlsplit(url).query,keep_blank_values=True)
        statuses=query.get('status',[])
        if statuses and (len(statuses)!=1 or statuses[0] not in ('open','completed')):
            return response(400,{'error':'Invalid latest filter'})
        needle=query.get('q',[''])[0].strip().casefold()
        matches=[item for item in self.items if needle in item['title'].casefold()
                 and (not statuses or item['completed']==(statuses[0]=='completed'))]
        value=max((item['id'] for item in matches),default=None)
        if self.mutate:self.items[0]['title']='unexpected mutation'
        return response(200,{'latest_id':value})


class LatestRecipeTests(unittest.TestCase):
    def setUp(self):
        ERRORS.clear();self.addCleanup(ERRORS.clear)

    def test_exact_json_rejects_wrong_types_mime_status_and_extra_fields(self):
        exact(response(200,{'latest_id':None}),200,{'latest_id':None})
        exact(response(200,{'latest_id':1}),200,{'latest_id':1})
        for candidate in (response(200,{'latest_id':True}),response(200,{'latest_id':'1'}),
                          response(200,{'latest_id':1,'extra':True}),response(201,{'latest_id':1}),
                          response(200,{'latest_id':1},'text/html')):
            with self.subTest(candidate=candidate),self.assertRaises(AssertionError):
                exact(candidate,200,{'latest_id':1})

    def test_api_cases_cover_filters_unicode_null_invalid_and_read_only(self):
        fixture=Fixture();items,checks=observe_api(fixture)
        self.assertEqual(len(items),3);self.assertEqual(len(checks),5)
        self.assertEqual(sum(urlsplit(url).path=='/feedback/latest' for url in fixture.calls),14)
        self.assertTrue(any('STRASSE' in url for url in fixture.calls))

    def test_wrong_results_invalid_status_acceptance_and_mutation_fail_closed(self):
        for fault in ('result','status','mutation'):
            fixture=Fixture();original=fixture.get
            def broken(url):
                result=original(url)
                if urlsplit(url).path=='/feedback/latest':
                    if fault=='result':return response(200,{'latest_id':999})
                    if fault=='status' and result.status==400:return response(200,result.json())
                return result
            fixture.get=broken;fixture.mutate=fault=='mutation'
            with self.subTest(fault=fault),self.assertRaises(AssertionError):observe_api(fixture)

    def test_console_exception_is_exact_single_use_and_page_scoped(self):
        guard=ConsoleGuard();page=object();other=object();url=ORIGIN+'/feedback/latest?q=probe'
        message=SimpleNamespace(type='error',text=guard.MESSAGE,location={'url':url})
        guard.injected(page,url);guard.observe(other,message);self.assertEqual(len(ERRORS),1)
        guard.observe(page,message);self.assertEqual(len(ERRORS),1)
        guard.observe(page,message);self.assertEqual(len(ERRORS),2)
        with self.assertRaises(AssertionError):guard.injected(page,ORIGIN+'/feedback/count')

    def test_harness_preserves_existing_submit_button_name(self):
        calls=[node for node in ast.walk(ast.parse(inspect.getsource(observe_ui)))
               if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
               and node.func.attr=='get_by_role' and node.args and isinstance(node.args[0],ast.Constant)
               and node.args[0].value=='button']
        names=[ast.literal_eval(kw.value) for call in calls for kw in call.keywords if kw.arg=='name']
        self.assertIn('Submit feedback',names);self.assertNotIn('Add',names)

    def test_not_enabled_until_real_browser_qualification(self):
        for scenario in ('feedback-board-latest-api-v1','feedback-board-latest-ui-v1'):
            with self.assertRaisesRegex(ValueError,'unqualified'):recipe_for(scenario)
        with self.assertRaises(ValueError):run('../arbitrary.py')
