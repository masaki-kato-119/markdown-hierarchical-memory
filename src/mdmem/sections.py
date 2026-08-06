"""Heading-based section lookup/extraction, used for §4 (append-to-section) and
§9/§10 (split a section into its own file)."""
from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def _find_heading_line(lines: list[str], heading: str) -> tuple[int, int] | None:
    """Return (line_index, level) of the first heading whose text matches
    `heading` (case-insensitive, exact)."""
    target = heading.strip().lower()
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group(2).strip().lower() == target:
            return i, len(m.group(1))
    return None


def find_section_bounds(body: str, heading: str) -> tuple[int, int] | None:
    """Return (start, end) line indices (end exclusive) spanning the heading line
    and its content, up to (but excluding) the next heading of equal-or-lower
    level, or end of file."""
    lines = body.splitlines()
    found = _find_heading_line(lines, heading)
    if found is None:
        return None
    start, level = found
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return start, end


def list_headings(body: str) -> list[str]:
    """All heading texts in `body`, in order. Used to give a helpful error
    (rather than a bare "not found") when a section lookup fails -- exact
    heading matching (see _find_heading_line) is easy to miss by a stray
    space or a `#` count the caller didn't expect."""
    out = []
    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append(m.group(2).strip())
    return out


def append_under_section(body: str, heading: str, addition: str) -> str | None:
    """Insert `addition` at the end of the named section's content. Returns None
    if the heading isn't found (caller decides whether to append elsewhere)."""
    bounds = find_section_bounds(body, heading)
    if bounds is None:
        return None
    lines = body.splitlines()
    start, end = bounds
    # Insert after the section's last non-blank line, not after any trailing
    # blank lines that separate it from the next heading.
    insert_at = end
    while insert_at > start and lines[insert_at - 1] == "":
        insert_at -= 1
    insertion = addition.rstrip("\n").splitlines()
    new_lines = lines[:insert_at] + insertion + lines[insert_at:]
    return "\n".join(new_lines) + ("\n" if body.endswith("\n") else "")


def extract_section(body: str, heading: str) -> tuple[str, str] | None:
    """Remove the named section from `body`. Returns (extracted_text, remaining_body),
    or None if the heading isn't found."""
    bounds = find_section_bounds(body, heading)
    if bounds is None:
        return None
    lines = body.splitlines()
    start, end = bounds
    extracted = "\n".join(lines[start:end]).strip("\n")
    remaining = "\n".join(lines[:start] + lines[end:])
    return extracted, remaining
