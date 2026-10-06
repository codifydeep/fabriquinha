// Diagnostic preload only. Delegate unchanged callbacks/results; never wrap promises.
'use strict';
const vm = require('node:vm');
function install(target, publish) {
  let sequence=0, context=0; const ring=[], nodes=new WeakSet(), documents=new WeakSet();
  const record=(kind,ctx,data={})=>{ring.push({sequence:++sequence,context:ctx,kind,...data});if(ring.length>256)ring.shift();};
  function node(item,ctx) {
    if(!item || typeof item!=='object' || nodes.has(item))return item;
    nodes.add(item);
    const id=typeof item.id==='string' && /^[\w-]{1,80}$/.test(item.id)?item.id:'unknown';
    if(typeof item.addEventListener==='function') {
      const original=item.addEventListener;
      item.addEventListener=function(type,callback,...rest) {
        if(typeof callback!=='function')return Reflect.apply(original,this,[type,callback,...rest]);
        const event=['input','change','click','submit'].includes(type)?type:'other';
        record('event_registered',ctx,{node:id,event});
        return Reflect.apply(original,this,[type,function(...args){
          record('event_dispatched',ctx,{node:id,event,value:typeof item.value==='string'?item.value:null});
          return Reflect.apply(callback,this,args);
        },...rest]);
      };
    }
    if(typeof item.appendChild==='function') {
      const original=item.appendChild;
      item.appendChild=function(...args){const result=Reflect.apply(original,this,args);record('dom_append',ctx,{node:id,count:this.children?.length??null});return result;};
    }
    return item;
  }
  function sandbox(value) {
    if(!value || typeof value!=='object')return;
    const ctx=++context;record('context_created',ctx);
    const doc=value.document;
    if(doc && !documents.has(doc)) {
      documents.add(doc);
      for(const method of ['getElementById','querySelector'])if(typeof doc[method]==='function') {
        const original=doc[method];doc[method]=function(...args){return node(Reflect.apply(original,this,args),ctx);};
      }
    }
    if(typeof value.fetch==='function') {
      const original=value.fetch;
      value.fetch=function(url,options,...rest) {
        let query=null;try{query=new URL(String(url),'http://diagnostic.invalid').searchParams.get('query');}catch{}
        const method=['GET','POST','PATCH','DELETE'].includes(options?.method)?options.method:'GET';
        record('fetch_started',ctx,{method,query});
        return Reflect.apply(original,this,[url,options,...rest]);
      };
    }
    for(const method of ['setTimeout','setInterval'])if(typeof value[method]==='function') {
      const original=value[method];
      value[method]=function(callback,delay,...args){
        record('timer_registered',ctx,{timer:method,delay:Number.isFinite(delay)?delay:null});
        if(typeof callback!=='function')return Reflect.apply(original,this,[callback,delay,...args]);
        return Reflect.apply(original,this,[function(...values){record('timer_fired',ctx,{timer:method});return Reflect.apply(callback,this,values);},delay,...args]);
      };
    }
  }
  const original=target.createContext;
  target.createContext=function(value,...rest){sandbox(value);return Reflect.apply(original,this,[value,...rest]);};
  return ()=>publish({events:ring,total_events:sequence,truncated:sequence>ring.length});
}
module.exports={install};
if(require.main!==module && process.env.DELIVERY_EVENT_TRACE==='1') {
  const finish=install(vm,report=>process.stderr.write('\nDELIVERY_EVENT_TRACE_V1:'+JSON.stringify(report)+'\n'));
  process.once('exit',finish);
}
