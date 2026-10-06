"""Fixed, additive compilation capability. No test/lint relaxation or arbitrary config."""
import json

def enable_shared_build(original):
    value=json.loads(original)
    if value.get('extends')!='./tsconfig.json' or value.get('compilerOptions',{}).get('rootDir')!='server':raise PermissionError('unrecognized build contract')
    if value.get('include')!=['server/**/*.ts']:raise PermissionError('unexpected build scope')
    value['compilerOptions']['rootDir']='.'
    value['include']=['server/**/*.ts','shared/**/*.ts']
    return json.dumps(value,indent=2)+'\n'
