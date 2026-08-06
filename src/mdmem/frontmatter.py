"""Minimal YAML front matter parsing/dumping (spec §3).

Avoids an extra dependency (python-frontmatter) since the format is a simple
```
---
<yaml>
---
<body>
```
"""
from __future__ import annotations

import yaml

_DELIM = "---"


def parse(text: str) -> tuple[dict, str]:
    """Split raw file text into (frontmatter_dict, body). Missing/invalid
    front matter yields an empty dict and the original text as body."""
    if not text.startswith(_DELIM):
        return {}, text
    lines = text.split("\n")
    if lines[0].strip() != _DELIM:
        return {}, text
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIM:
            end_idx = i
            break
    if end_idx is None:
        return {}, text
    yaml_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    if body.startswith("\n"):
        body = body[1:]
    try:
        data = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid front matter YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("front matter must be a YAML mapping")
    return data, body


def dump(fm: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip("\n")
    body = body if body.startswith("\n") or body == "" else body
    return f"{_DELIM}\n{yaml_block}\n{_DELIM}\n{body}"
