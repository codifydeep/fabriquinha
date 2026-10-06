"""Single machine/user contract; never reinterpret historical receipts."""
CONTRACT=('Red requires a real executed behavioral assertion failure, exit 1, no ignored tests, and accepted=true. '
    'An absent module, import/configuration failure, or uncaught Error("not implemented") is not accepted Red. '
    'Create a minimal loadable scaffold and a behavior assertion before implementing the behavior. '
    'Inspect accepted and diagnostic after every test. Do not proceed to Green after rejected Red. '
    'Green requires the SAME test hash, base and validation image as accepted Red; implementation source is expected to change. '
    'Changed tests require new Red evidence. Never weaken baseline tests or fabricate past evidence.')

class EvidenceRejected(PermissionError):
    def __init__(self,code,**details):
        self.diagnostic=dict(code=code,**details,next_action=CONTRACT)
        super().__init__(code)

def red_mismatch(red,tests,base,image):
    if not red:return 'RED_MISSING'
    if not red['accepted']:return 'RED_NOT_ACCEPTED'
    if red['tests_sha256']!=tests:return 'RED_TESTS_CHANGED'
    if red['base']!=base:return 'RED_BASE_CHANGED'
    if red['image']!=image:return 'RED_VALIDATOR_CHANGED'
    return None

def rejection(phase,accepted,output,exit_code,complete,failures):
    if accepted:return dict(code='ACCEPTED',next_action='Green with unchanged tests' if phase=='red' else 'Continue full suite and independent review')
    if not complete:code='TEST_DISCOVERY_OR_IGNORED_TESTS'
    elif phase=='red' and exit_code==0:code='RED_ALREADY_GREEN'
    elif phase=='red' and (not failures or 'ERR_ASSERTION' not in output):code='RED_NOT_BEHAVIORAL_ASSERTION'
    else:code='VALIDATION_FAILED'
    return dict(code=code,next_action=CONTRACT)
