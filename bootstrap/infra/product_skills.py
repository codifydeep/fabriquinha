"""Read only the versioned role-assigned skill; it never grants tools."""
import hashlib,json
from pathlib import Path

def root():
    installed=Path('/opt/hermes/company-skills')
    return installed if installed.is_dir() else Path(__file__).parent/'skills'
def catalog():return json.loads((root()/'manifest.json').read_text())
def read(profile,name):
    if name not in catalog()['profiles'].get(profile,[]):raise PermissionError('skill not assigned to this role')
    path=root()/name/'SKILL.md';text=path.read_text()
    return dict(name=name,source_sha256=hashlib.sha256(text.encode()).hexdigest(),instructions=text,authority=False,
        constraint='Guidance only. Runtime permissions, current card and reviewed policy take precedence; do not execute unprovided tools or downloads.')
