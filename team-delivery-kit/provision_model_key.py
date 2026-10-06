"""Copy only the approved OpenRouter key into the proxy-only Docker volume."""
import subprocess

from evalctl import process_env, PROJECT

SOURCE = '''from pathlib import Path
p=Path('/opt/data/profiles/techlead/.env')
values=[line.split('=',1)[1].strip() for line in p.read_text().splitlines()
        if line.startswith('OPENROUTER_API_KEY=')]
if len(values)!=1 or len(values[0])<20:
 raise SystemExit('approved key absent or ambiguous')
print(values[0],end='')
'''
RECEIVER = '''import os,sys
value=sys.stdin.buffer.read().strip()
if len(value)<20 or len(value)>4096 or b'\\n' in value:
 raise SystemExit('invalid key material')
path='/secret/openrouter.key'
fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o400)
os.write(fd,value)
os.fchown(fd,10000,10000)
os.close(fd)
print('approved model key provisioned in proxy-only volume')
'''


def main():
    env = process_env()
    key = subprocess.check_output(['docker', 'exec', 'estudo-hermes', 'python3', '-c', SOURCE],
                                  env=env, stderr=subprocess.PIPE, timeout=15)
    if not 20 <= len(key) <= 4096:
        raise ValueError('unexpected approved key length')
    volume = PROJECT + '_model_secret'
    subprocess.run(['docker', 'volume', 'inspect', volume],
                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0',
                    *__import__('docker_grouping').args('key-provision', namespace=PROJECT),
                    '--label', 'delivery-kit.owner=' + PROJECT + '-model-provision',
                    '--mount', 'type=volume,src=' + volume + ',dst=/secret',
                    '--entrypoint', 'python', 'delivery-kit-hermes-runtime:20260928.1',
                    '-c', RECEIVER], input=key, env=env, check=True, timeout=30)


if __name__ == '__main__':
    main()
