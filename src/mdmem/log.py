"""Change log (spec §10, §17): every mutating tool call appends an entry here so
mis-judgments can be reviewed and manually reverted later. Logging is done by the
mutating operations themselves, not left to the caller to remember."""
from __future__ import annotations

import re
from pathlib import Path

from .models import ARCHIVE_DIR, LOG_NAME, now_stamp

_ACTOR_RE = re.compile(r"^- actor: (.*)$")

_HEADER = (
    "# Manager Agent Change Log\n\n"
    "Append-only. Each entry records what changed and why, so a later reviewer "
    "can revert a mis-judged action by hand (spec §17).\n"
)


def log_path(root: Path) -> Path:
    return root / ARCHIVE_DIR / LOG_NAME


def append(root: Path, action: str, targets: list[str], rationale: str, actor: str = "unspecified") -> None:
    path = log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(_HEADER, encoding="utf-8", newline="\n")
    entry = (
        f"\n## {now_stamp()} — {action}: {', '.join(targets)}\n"
        f"- actor: {actor}\n"
        f"- rationale: {rationale}\n"
    )
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(entry)


def list_actors(root: Path) -> dict[str, int]:
    """Every `actor` value that has been written to the log, with entry counts.

    `actor` is free-form like `type`, and drifted the same way once nothing made the
    existing values visible: one real store accumulated claude / cursor / cursor-auto
    / memory-manager for what were three agents. Unlike `type` this cannot be read
    off the files -- actors exist only in log history -- so it is counted here.
    """
    path = log_path(root)
    if not path.exists():
        return {}
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _ACTOR_RE.match(line)
        if m:
            actor = m.group(1).strip()
            counts[actor] = counts.get(actor, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
