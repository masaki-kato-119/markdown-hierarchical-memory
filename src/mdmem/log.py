"""Change log (spec §10, §17): every mutating tool call appends an entry here so
mis-judgments can be reviewed and manually reverted later. Logging is done by the
mutating operations themselves, not left to the caller to remember."""
from __future__ import annotations

from pathlib import Path

from .models import ARCHIVE_DIR, LOG_NAME, now_stamp

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
