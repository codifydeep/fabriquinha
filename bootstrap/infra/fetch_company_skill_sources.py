"""Download pinned upstream text only; never execute upstream installers."""
import hashlib,json,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]/'vendor/company-skills'
SOURCES={
 'karpathy':('multica-ai/andrej-karpathy-skills',['skills/karpathy-guidelines/SKILL.md','README.md']),
 'frontend-design':('anthropics/skills',['skills/frontend-design/SKILL.md','skills/frontend-design/LICENSE.txt']),
 '3d-web-experience':('sickn33/agentic-awesome-skills',['skills/3d-web-experience/SKILL.md','LICENSE']),
 'defuddle':('kepano/defuddle',['README.md','LICENSE','package.json']),
}
def get(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Hermes-company-skill-audit'})
    with urllib.request.urlopen(req,timeout=40) as r:return r.read()
def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    lock=ROOT/'sources.lock.json'
    if lock.exists():raise RuntimeError('Pinned sources already downloaded; no implicit upgrade')
    result={}
    for name,(repo,paths) in SOURCES.items():
        sha=json.loads(get('https://api.github.com/repos/'+repo+'/commits/HEAD'))['sha']
        result[name]={'repository':repo,'commit':sha,'files':{}}
        for path in paths:
            data=get('https://raw.githubusercontent.com/'+repo+'/'+sha+'/'+path)
            target=ROOT/name/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            result[name]['files'][path]=hashlib.sha256(data).hexdigest()
    lock.write_text(json.dumps(result,indent=2)+'\n');print(lock)
if __name__=='__main__':main()
