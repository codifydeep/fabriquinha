"""Admission checks: policy entries alone do not grant executable adapters."""
import re
from product_policy import CAPABILITIES

def preflight(capability,registration):
    if capability not in CAPABILITIES:raise PermissionError('unknown capability')
    if registration.get('adapter')!=CAPABILITIES[capability]['adapter'] or not registration.get('validated_receipt'):raise PermissionError('tested adapter receipt required')
    if registration['adapter'] in ('lobby-ts','document') and not re.fullmatch(r'sha256:[0-9a-f]{64}',registration.get('image','')):raise PermissionError('pinned local validator required')
    return True
