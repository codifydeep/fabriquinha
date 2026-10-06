import json
import pathlib
import subprocess
import unittest


class EventTraceTests(unittest.TestCase):
    def test_delegates_results_promises_callbacks_and_order(self):
        path=pathlib.Path(__file__).parents[1]/'broker/event_trace.cjs'
        script=r'''const {install}=require(process.argv[1]);let report,callback,observed;
const finish=install({createContext:s=>s},r=>report=r);
const vm={createContext:s=>s};const done=install(vm,r=>observed=r);
const promise=Promise.resolve('ok'),listeners={};
const item={id:'search',value:'fixture',children:[],addEventListener(t,c){listeners[t]=c;return 7;},appendChild(x){this.children.push(x);return x;}};
const context=vm.createContext({document:{getElementById:()=>item},fetch:()=>promise,setTimeout(c){callback=c;return 3;}});
const actual=context.document.getElementById('search');let result=0;
const registration=actual.addEventListener('input',function(){result=this===item?5:0;});
listeners.input.call(item);const timer=context.setTimeout(()=>result++,0);callback();
const child={},append=actual.appendChild(child);const same=context.fetch('/api?query=fixture')===promise;
done();finish();console.log(JSON.stringify({registration,timer,result,same,appendSame:append===child,events:observed.events}));'''
        result=subprocess.run(['node','-e',script,str(path)],capture_output=True,text=True,check=True)
        data=json.loads(result.stdout)
        self.assertEqual((data['registration'],data['timer'],data['result']),(7,3,6))
        self.assertTrue(data['same']);self.assertTrue(data['appendSame'])
        kinds=[e['kind'] for e in data['events']]
        self.assertLess(kinds.index('event_dispatched'),kinds.index('timer_fired'))
        self.assertEqual([e['sequence'] for e in data['events']],list(range(1,len(kinds)+1)))
