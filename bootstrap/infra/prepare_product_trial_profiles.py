"""Copy only the selected provider credential; no Telegram/Git credentials."""
import os
from pathlib import Path
import yaml
from dotenv import dotenv_values

target=Path('/trial-profiles');target.mkdir(exist_ok=True)
for name in os.environ.get('TRIAL_PROFILES','backend_data,techlead').split(','):
    from product_policy import ROLES
    if name not in ROLES:raise ValueError('unregistered trial profile')
    source=Path('/source/profiles')/name
    config=yaml.safe_load((source/'config.yaml').read_text())
    if config['model']!={'default':'deepseek/deepseek-v4-flash-0731','provider':'openrouter'}:
        raise ValueError('unexpected model; no automatic substitution')
    values=dotenv_values(source/'.env')
    # Dashboard Keys was configured in techlead, not the author profile.
    # Reuse only this explicitly scoped provider secret for the isolated trial.
    key=values.get('OPENROUTER_API_KEY') or dotenv_values('/source/profiles/techlead/.env').get('OPENROUTER_API_KEY') or dotenv_values('/source/.env').get('OPENROUTER_API_KEY')
    if not key:raise ValueError('OpenRouter credential unavailable')
    destination=target/'profiles'/name;destination.mkdir(parents=True,exist_ok=True)
    destination.chmod(0o700)
    clean=dict(model=config['model'],agent={'max_turns':40,'reasoning_effort':'medium'},fallback_providers=[],
               toolsets=['kanban'],kanban={'dispatch_in_gateway':False,'max_in_progress':2,'max_in_progress_per_profile':1},
               display={'interface':'cli'})
    (destination/'config.yaml').write_text(yaml.safe_dump(clean))
    (destination/'.env').write_text('OPENROUTER_API_KEY='+key+'\n')
    (destination/'.env').chmod(0o600)
    (destination/'.no-bundled-skills').touch()
print('Prepared requested isolated profiles; only OpenRouter credential copied, no secrets printed.')
