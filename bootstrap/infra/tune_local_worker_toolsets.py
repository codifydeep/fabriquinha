#!/usr/bin/env python3
"""Keep local Qwen worker prompts small without changing Telegram toolsets."""

from pathlib import Path

import yaml


PROFILES_ROOT = Path("/opt/data/profiles")
ENGINEERING = (
    "cto",
    "techlead",
    "backend_data",
    "frontend",
    "mobile",
    "devops",
    "quality_security",
)
RESEARCH = ("produto", "designer")


def update(profile: str, toolsets: list[str]) -> None:
    path = PROFILES_ROOT / profile / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    platform = data.setdefault("platform_toolsets", {})
    platform["cli"] = toolsets
    temporary = path.with_suffix(".yaml.new")
    temporary.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    temporary.chmod(path.stat().st_mode & 0o777)
    temporary.replace(path)
    print(f"{profile}: cli={','.join(toolsets)}")


def main() -> None:
    for profile in ENGINEERING:
        update(profile, ["terminal", "file"])
    for profile in RESEARCH:
        update(profile, ["web", "terminal", "file"])


if __name__ == "__main__":
    main()
