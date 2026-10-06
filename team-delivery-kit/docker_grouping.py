"""Presentation labels for controller-created jobs, isolated from core Compose."""
import os
import re


def labels(service='job', namespace=None, kind='tests'):
    namespace = namespace or os.environ.get('DELIVERY_KIT_COMPOSE_PROJECT', 'delivery-kit-eval')
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}', namespace):
        raise ValueError('invalid delivery Docker namespace')
    if kind not in ('tests', 'homologation') or not re.fullmatch(r'[a-z0-9-]+', service):
        raise ValueError('invalid delivery Docker group')
    return {'com.docker.compose.project': namespace + '-' + kind,
            'com.docker.compose.service': service,
            'com.docker.compose.oneoff': 'True',
            'delivery-kit.lifecycle': kind}


def args(service='job', namespace=None, kind='tests'):
    return [part for key, value in labels(service, namespace, kind).items()
            for part in ('--label', key + '=' + value)]


def grouped_create(method, path, payload, namespace):
    # Central boundary covers seeds, locks, workers, snapshots and suite runners.
    if method == 'POST' and path.startswith('/containers/create'):
        payload = {**payload, 'Labels': {**(payload.get('Labels') or {}),
                                       **labels(namespace=namespace)}}
    return payload
