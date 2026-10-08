"""Bind independent feature QA to durable, same-image regression evidence."""
import hashlib
import json
from pathlib import Path
import re

COMMON = ('source_sha', 'deployed_container_id', 'application_image', 'runtime_env')


def receipt_key(identity):
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def reference(directory, receipt):
    key = receipt_key(receipt['identity'])
    path = Path(directory) / (key + '.json')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('unsafe baseline QA receipt')
    raw = path.read_bytes()
    if json.loads(raw) != receipt:
        raise ValueError('baseline QA return differs from durable receipt')
    return {'receipt_key': key, 'receipt_sha256': hashlib.sha256(raw).hexdigest(),
            'screenshot_sha256': receipt.get('screenshot_sha256')}


def verify(directory, proof, candidate_identity, baseline_config, recipe_hash):
    if (not isinstance(proof, dict) or set(proof) !=
            {'receipt_key', 'receipt_sha256', 'screenshot_sha256'} or
            any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value)
                for value in proof.values())):
        raise ValueError('exact baseline QA reference required')
    folder = Path(directory)
    path = folder / (proof['receipt_key'] + '.json')
    screenshot = path.with_suffix('.png')
    if (folder.is_symlink() or path.is_symlink() or screenshot.is_symlink()
            or not path.is_file() or path.stat().st_size > 65536
            or not screenshot.is_file() or not 0 < screenshot.stat().st_size <= 10485760):
        raise ValueError('unsafe baseline QA evidence')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != proof['receipt_sha256']:
        raise ValueError('baseline QA receipt drift')
    receipt = json.loads(raw)
    identity = receipt.get('identity', {})
    if (receipt.get('status') != 'passed' or receipt.get('cleanup') != 'passed'
            or receipt.get('automated') is not True
            or receipt.get('result', {}).get('status') != 'passed'
            or receipt.get('result', {}).get('source_sha') != candidate_identity['source_sha']
            or set(identity) != set(COMMON) | {'config', 'scenario_sha256'}
            or any(identity.get(key) != candidate_identity[key] for key in COMMON)
            or identity.get('config') != baseline_config
            or identity.get('scenario_sha256') != recipe_hash
            or receipt_key(identity) != proof['receipt_key']
            or receipt.get('screenshot_sha256') != proof['screenshot_sha256']
            or hashlib.sha256(screenshot.read_bytes()).hexdigest() != proof['screenshot_sha256']):
        raise ValueError('baseline QA must be current, passed and same deployment')
    return receipt
