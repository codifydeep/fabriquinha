"""Operator-side, fixed-contract offline tests and exact post-deploy HTTP QA."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request

from portable_contract import validate
from test_runner_policy import unacceptable_output


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError('post-deploy redirect forbidden')


def qa_case_failure(message, case, contract):
    """Disambiguate checks sharing a URL without changing their acceptance."""
    marker = ''
    if sum(item['path'] == case['path'] for item in contract['qa_cases']) > 1:
        digest = hashlib.sha256(json.dumps(case, sort_keys=True,
                                          separators=(',', ':')).encode()).hexdigest()
        marker = ' [qa-case=' + digest + ']'
    return ValueError(message + marker + ': ' + case['path'])


def run_frozen_tests(snapshot, contract):
    from docker_grouping import args as docker_group_args
    contract = validate(contract)
    snapshot = Path(snapshot).resolve(strict=True)
    if not snapshot.is_dir() or snapshot.is_symlink():
        raise ValueError('snapshot must be a real directory')
    # The operator-supplied image is digest-pinned. The worker supplies neither
    # argv nor image. There is no network, credential, socket or writable source.
    result = subprocess.run([
        'docker', 'run', '--rm', '--network', 'none', '--read-only',
        *docker_group_args('frozen-suite'),
        '--user', '10000:10000', '--cap-drop', 'ALL',
        '--security-opt', 'no-new-privileges', '--memory', '256m', '--cpus', '1',
        '--pids-limit', '96', '--tmpfs', '/tmp:rw,nosuid,nodev,size=32m',
        '--env', 'PYTHONDONTWRITEBYTECODE=1',
        '--mount', f'type=bind,source={snapshot},target=/delivery,readonly',
        '--workdir', '/delivery', '--entrypoint', contract['test_command'][0],
        contract['test_image'], *contract['test_command'][1:]],
        capture_output=True, text=True, timeout=120)
    output = (result.stdout + '\n' + result.stderr)[-12000:]
    if (result.returncode or not re.search(contract['test_success_pattern'], output)
            or unacceptable_output(output)):
        raise ValueError('frozen full-suite test command failed')
    match = re.search(contract['test_count_pattern'], output)
    count = int(match.group(1)) if match else 0
    if count < len(contract['test_files']):
        raise ValueError('frozen suite executed fewer tests than declared test files')
    return {'status': 'passed', 'command': contract['test_command'],
            'tests': count, 'output_sha256': hashlib.sha256(output.encode()).hexdigest()}


def verify_http_qa(base_url, source_sha, contract):
    contract = validate(contract)
    if not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{1,4}', base_url):
        raise ValueError('QA endpoint must bind to loopback')
    if not re.fullmatch(r'[0-9a-f]{40}', source_sha):
        raise ValueError('invalid source SHA')
    opener = urllib.request.build_opener(NoRedirect())
    for case in contract['qa_cases']:
        try:
            response = opener.open(base_url + case['path'], timeout=3)
        except urllib.error.HTTPError as error:
            error.close()
            raise qa_case_failure('post-deploy status mismatch', case, contract) from error
        with response:
            if response.status != case['status']:
                raise qa_case_failure('post-deploy QA mismatch', case, contract)
            if 'expected_json' in case:
                body = json.load(response)
                expected = case['expected_json']
                if case.get('bind_source_sha', True):
                    expected = expected | {'source_sha': source_sha}
                if body != expected:
                    raise qa_case_failure('post-deploy QA mismatch', case, contract)
            else:
                if not response.headers.get('Content-Type', '').lower().startswith(case['content_type']):
                    raise qa_case_failure('post-deploy content type mismatch', case, contract)
                body = response.read(65537)
                if len(body) > 65536:
                    raise qa_case_failure('post-deploy text response too large', case, contract)
                content = body.decode('utf-8')
                if any(value not in content for value in case['text_contains']):
                    raise qa_case_failure('post-deploy content mismatch', case, contract)
    return {'status': 'passed', 'source_sha': source_sha,
            'url': base_url, 'cases': len(contract['qa_cases'])}


def verify_docker_deployment(container_name, base_url, source_sha, contract):
    """Tie loopback QA to a running, exact-SHA Docker image."""
    if not re.fullmatch(r'[a-z][a-z0-9_.-]{2,127}', container_name):
        raise ValueError('invalid deployment container')
    if not re.fullmatch(r'http://127\.0\.0\.1:([1-9][0-9]{1,4})', base_url):
        raise ValueError('deployment URL must use loopback')
    port = base_url.rsplit(':', 1)[1]
    details = json.loads(subprocess.check_output(['docker', 'inspect', container_name], text=True))
    if len(details) != 1 or details[0]['Name'] != '/' + container_name:
        raise ValueError('deployment identity mismatch')
    container = details[0]
    if not container['State']['Running'] or container['HostConfig'].get('Privileged'):
        raise ValueError('deployment not safely running')
    requested = container['HostConfig'].get('PortBindings') or {}
    published = container['NetworkSettings'].get('Ports') or {}
    if (not any(binding == [{'HostIp': '127.0.0.1', 'HostPort': port}]
                for binding in published.values())
            or not any(len(binding or []) == 1 and binding[0].get('HostIp') == '127.0.0.1'
                       and binding[0].get('HostPort') in (port, '', None)
                       for binding in requested.values())):
        raise ValueError('deployment is not bound to expected loopback port')
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', container['Image']], text=True))
    if len(image) != 1 or image[0]['Config']['Labels'].get('delivery-kit.source-sha') != source_sha:
        raise ValueError('deployment image SHA mismatch')
    result = verify_http_qa(base_url, source_sha, contract)
    result.update(container=container_name, image_id=image[0]['Id'])
    return result
