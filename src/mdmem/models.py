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
#
# `howto` is here because the store already had a memory/howto/ file that this set
# would have rejected: the agent wanted that directory, was refused, and settled for
# reference/ with type: howto. §2 calls directories an aid rather than the real
# structure, so the list following actual use costs nothing and stops the same
# workaround recurring.
ALLOWED_DIRS = {"concepts", "projects", "reference", "howto"}

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


def size_attention(body: str) -> str | None:
    """A non-binding nudge for the Manager Agent when a file crosses a §5 threshold.

    The server deliberately does not act on this — §11/§17 keep the split/summarize
    judgment with the calling LLM. It exists because the passive `size_level` field
    was demonstrably not enough on its own: one file reached 1126 lines (3.7x the
    300-line threshold) across six consecutive appends without §9's matrix ever
    being consulted, because nothing in the response asked for a decision. Returning
    prose the agent has to read through makes ignoring it a choice, not an oversight.
    """
    n = line_count(body)
    low, high = SIZE_LEVEL_THRESHOLDS
    if n > high:
        return (
            f"This file is now {n} lines, past the {high}-line threshold (spec §5). "
            "Apply the §9 matrix before continuing: split_memory_file if it has drifted "
            "across several themes, summarize_and_archive_memory_file if importance x "
            "reference-frequency is low. Archiving needs explicit user confirmation (§11)."
        )
    if n > low and not _has_sections(body):
        # §5's prescription at this size is "organize into sections", so saying it to
        # a file that is already organized is advice with nothing to act on. Ten of
        # the twelve files in the first real audit were in exactly that state: the
        # nudge fired, the answer was "already done". Advice that reliably needs no
        # action is how the plain size_level number came to be ignored — the failure
        # this whole signal exists to correct — so it stays quiet here.
        return (
            f"This file is now {n} lines (spec §5) and has no section headings. Organize "
            "it into sections now, so a later split_memory_file has clean seams to cut along."
        )
    return None


def _has_sections(body: str) -> bool:
    return any(line.startswith("## ") for line in body.splitlines())


# spec §13's forget condition
FORGET_AFTER_DAYS = 180
FORGET_BELOW_ACCESS_COUNT = 3


def is_archive_candidate(
    fm: dict, now: datetime | None = None, days: int = FORGET_AFTER_DAYS
) -> bool:
    """spec §13: access_count < 3 AND last_access older than `days` AND pinned != true.

    `days` is adjustable because the 180-day default makes the condition unreachable
    in a young store -- the first real audit returned nothing at all, and could not
    have returned anything for another six months, which leaves no way to see whether
    the rule behaves as intended. Lowering it is for inspection and tuning; the
    default is the spec's.

    This only reports candidacy — actual archiving requires explicit confirmation
    (spec §11), so callers must treat the result as a suggestion, not an action.
    """
    if fm.get("pinned"):
        return False
    if int(fm.get("access_count", 0)) >= FORGET_BELOW_ACCESS_COUNT:
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
    return age_days > days
