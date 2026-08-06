"""Front matter shape and size-level helpers (spec §3, §5)."""
from __future__ import annotations

import re
from datetime import datetime, timezone

INDEX_NAME = "index.md"
LOG_NAME = "_manager_log.md"
ARCHIVE_DIR = "archive"

# spec §2 layout. archive/ is reserved for the manager (move_to_archive /
# summarize_and_archive) and is deliberately excluded here -- create_file
# should never place a fresh file directly into archive/.
ALLOWED_DIRS = {"concepts", "projects", "reference"}

# `id` becomes a filename component (root / dir / f"{id}.md") and is caller
# (LLM-)supplied. Without this, a crafted id like "../../etc/evil" writes
# outside the memory root entirely -- confirmed exploitable in practice, not
# theoretical. Deliberately restrictive (matches the wikilink-friendly ids
# already in use) rather than trying to blocklist ".."/separators piecemeal.
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

DEFAULT_IMPORTANCE = 0.5

# spec §5
SIZE_LEVEL_THRESHOLDS = (100, 300)  # <=100 -> 1, <=300 -> 2, else 3


def now_stamp() -> str:
    """Fine-grained ISO-8601 stamp used for `updated` (spec §16 calls this a
    'simple version value' carried by the `updated` timestamp)."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def today_date() -> str:
    return datetime.now().astimezone().date().isoformat()


def new_frontmatter(
    id: str,
    type: str,
    tags: list[str] | None = None,
    importance: float = DEFAULT_IMPORTANCE,
    pinned: bool = False,
    parent: list[str] | None = None,
) -> dict:
    ts = now_stamp()
    return {
        "id": id,
        "type": type,
        "importance": importance,
        "pinned": pinned,
        "created": today_date(),
        "updated": ts,
        "access_count": 0,
        "last_access": today_date(),
        "parent": parent or [],
        "tags": tags or [],
    }


def line_count(body: str) -> int:
    if body == "":
        return 0
    return len(body.splitlines())


def size_level(body: str) -> int:
    n = line_count(body)
    low, high = SIZE_LEVEL_THRESHOLDS
    if n <= low:
        return 1
    if n <= high:
        return 2
    return 3


def is_archive_candidate(fm: dict, now: datetime | None = None) -> bool:
    """spec §13: access_count < 3 AND last_access > 180 days ago AND pinned != true.

    This only reports candidacy — actual archiving requires explicit confirmation
    (spec §11), so callers must treat the result as a suggestion, not an action.
    """
    if fm.get("pinned"):
        return False
    if int(fm.get("access_count", 0)) >= 3:
        return False
    last_access = fm.get("last_access")
    if not last_access:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last_access))
    except ValueError:
        return False
    if now is None:
        now = datetime.now(last_dt.tzinfo) if last_dt.tzinfo else datetime.now()
    elif last_dt.tzinfo and now.tzinfo is None:
        now = now.astimezone()
    age_days = (now - last_dt).days
    return age_days > 180
