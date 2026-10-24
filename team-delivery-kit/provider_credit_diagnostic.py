"""Read-only provider metadata probe. Never resolves a pause or calls a model.

Run PROGRAM inside the existing proxy only under sealed, idle maintenance.
Output is a financial summary, not the provider response or key identity.
"""
import math


def summarize(credits, info):
    def number(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    if not isinstance(credits, dict) or not isinstance(info, dict):
        raise ValueError('invalid provider metadata')
    if not all(number(credits.get(k)) for k in ('total_credits', 'total_usage')):
        raise ValueError('invalid account credit metadata')
    limit, remaining = info.get('limit'), info.get('limit_remaining')
    if not all(k in info for k in ('limit', 'limit_remaining')):
        raise ValueError('missing key allowance metadata')
    unlimited = limit is None and remaining is None
    if not unlimited and not (number(limit) and number(remaining)):
        raise ValueError('invalid key allowance metadata')
    return dict(account_balance_usd=credits['total_credits']-credits['total_usage'],
                key_limit_usd=limit, key_remaining_usd=remaining,
                key_unlimited=unlimited, model_calls=0, pause_removed=False)


PROGRAM = r'''
import sys,json,os,hashlib,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,'/')
import model_proxy as m
namespace={}
exec(sys.stdin.read(16384),namespace)
counter=Path(m.COUNTER_PATH)
paths=(counter,counter.with_name('provider-pause.json'))
def fingerprints():
 result=[]
 for path in paths:
  if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:
   raise ValueError('bounded existing regular meter files required')
  result.append(hashlib.sha256(path.read_bytes()).hexdigest())
 return result
before=fingerprints()
key=Path('/secret/openrouter.key').read_text().strip()
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
opener=urllib.request.build_opener(NoRedirect())
def official(endpoint):
 request=urllib.request.Request('https://openrouter.ai/api/v1/'+endpoint,
  headers={'Authorization':'Bearer '+key},method='GET')
 try:
  with opener.open(request,timeout=20) as response:
   raw=response.read(65537)
   if len(raw)>65536:raise ValueError('metadata response too large')
   data=json.loads(raw)
   if not isinstance(data,dict) or not isinstance(data.get('data'),dict):
    raise ValueError('invalid metadata envelope')
   return {'status':response.status,'data':data['data']}
 except urllib.error.HTTPError as error:
  return {'status':error.code}
 except (OSError,ValueError):
  return {'status':'unavailable'}
credits=official('credits');info=official('key')
result=dict(credits_http_status=credits['status'],key_http_status=info['status'],
 model_calls=0,pause_removed=False,calls=m.load_calls())
if credits['status']==200 and info['status']==200:
 try:result.update(namespace['summarize'](credits['data'],info['data']))
 except ValueError:result['metadata_valid']=False
after=fingerprints()
if before!=after:raise ValueError('meter changed during diagnostic')
result.update(meter_unchanged=True,meter_sha256=after)
print(json.dumps(result,sort_keys=True))
'''
