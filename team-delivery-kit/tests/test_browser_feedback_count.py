import json
import unittest
from types import SimpleNamespace
from browser_feedback_count import exact_json,observe_api,ConsoleGuard,LAST_ERRORS,ORIGIN,run


def response(status,value,mime='application/json'):
    return SimpleNamespace(status=status,headers={'content-type':mime},json=lambda:value)


class CountRecipeTests(unittest.TestCase):
    def test_exact_count_not_boolean_extra_field_or_wrong_status(self):
        exact_json(response(200,{'count':1}),200,{'count':1})
        for candidate in (response(201,{'count':1}),response(200,{'count':True}),
                          response(200,{'count':1,'extra':0}),response(200,{'count':1},'text/html')):
            with self.subTest(candidate=candidate),self.assertRaises(AssertionError):
                exact_json(candidate,200,{'count':1})

    def test_all_api_negative_cases_and_read_only_checks_are_executed(self):
        class Fixture:
            def __init__(self): self.titles=[];self.calls=[];self.reads=0
            def post(self,url,data=None):
                if url.endswith('/complete'):return response(200,{})
                self.titles.append(data['title'])
                return response(201,{'id':len(self.titles)})
            def get(self,url):
                self.calls.append(url)
                if not '/count' in url:return response(200,{'items':list(self.titles)})
                query=url.split('/count',1)[1]
                counts={'':3,'?status=open':2,'?status=completed':1,'?q=match%20qa':2,
                    '?status=open&q=MATCH%20QA':1,'?q=match%20qa&status=completed':1,
                    '?q=STRASSE':1,'?q=absent-count-needle':0,'?q=%20%20':3,
                    '?q=%27%20OR%201%3D1%20--':0}
                if query in counts:return response(200,{'count':counts[query]})
                return response(400,{'error':'Invalid count filter'})
        fixture=Fixture();self.assertEqual(len(observe_api(fixture)),7)
        self.assertEqual(len([url for url in fixture.calls if '/count' in url]),14)
        original=fixture.get
        fixture.get=lambda url:response(200,{'count':99}) if '?status=open&q=' in url else original(url)
        with self.assertRaises(AssertionError):observe_api(fixture)

    def test_only_single_exact_injected_error_is_allowed(self):
        LAST_ERRORS.clear();self.addCleanup(LAST_ERRORS.clear)
        guard=ConsoleGuard();page=object();url=ORIGIN+'/feedback/count?q=absent'
        message=SimpleNamespace(type='error',text=guard.MESSAGE,location={'url':url})
        guard.injected(page,url);guard.observe(page,message);self.assertFalse(LAST_ERRORS)
        guard.observe(page,message);self.assertEqual(len(LAST_ERRORS),1)
        with self.assertRaises(AssertionError):guard.injected(page,'https://unrelated.invalid/')

    def test_arbitrary_recipe_is_never_run(self):
        with self.assertRaises(ValueError):run('../arbitrary.py')
