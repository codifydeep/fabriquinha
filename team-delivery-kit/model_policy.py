"""Single versioned model policy for this evaluation installation."""

MODEL = 'anthropic/claude-haiku-5.5'
PREVIOUS_MODEL = 'deepseek/deepseek-v4.1-flash'
PROXY_BASE_URL = 'http://model-proxy:8080/api/v1'
PLACEHOLDER_KEY = 'offline-placeholder-not-a-credential'


def execution_base_url(identifier):
    import re
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', identifier):
        raise ValueError('invalid model execution identifier')
    return PROXY_BASE_URL.replace('/api/v1', '/executions/' + identifier + '/api/v1')
