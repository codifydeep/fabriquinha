#!/usr/bin/env python3
"""Ensure implementer profiles can resolve the requesting-code-review skill."""

from pathlib import Path


PROFILES_ROOT = Path("/opt/data/profiles")
PROFILES = ("backend_data", "frontend", "mobile", "devops")
GITHUB_ENTRY = "    - /opt/data/skills/software-development/github\n"
REVIEW_ENTRY = "    - /opt/data/skills/software-development/requesting-code-review\n"


def update_config(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    if REVIEW_ENTRY.strip() in source:
        return False
    if GITHUB_ENTRY not in source:
        raise RuntimeError(f"github external_dirs anchor missing in {path}")
    updated = source.replace(GITHUB_ENTRY, GITHUB_ENTRY + REVIEW_ENTRY, 1)
    temp = path.with_suffix(".yaml.new")
    temp.write_text(updated, encoding="utf-8")
    temp.chmod(path.stat().st_mode & 0o777)
    temp.replace(path)
    return True


def main() -> None:
    missing_skill = Path(
        "/opt/data/skills/software-development/requesting-code-review/SKILL.md"
    )
    if not missing_skill.is_file():
        raise SystemExit(f"required skill missing: {missing_skill}")
    for profile in PROFILES:
        path = PROFILES_ROOT / profile / "config.yaml"
        changed = update_config(path)
        print(f"{profile}: {'updated' if changed else 'already-ok'}")


if __name__ == "__main__":
    main()
