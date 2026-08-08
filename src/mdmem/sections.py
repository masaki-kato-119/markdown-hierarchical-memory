"""Heading-based section lookup/extraction, used for §4 (append-to-section) and
§9/§10 (split a section into its own file)."""
from __future__ import annotations

import re

from .errors import ValidationError

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_LINK_LINE_RE = re.compile(r"^-\s+\[\[[^\[\]|]+\]\]$")


def _end_excluding_file_links(lines: list[str], start: int, end: int) -> int:
    """Pull `end` back past a run of §12 link lines sitting at the very end of the file.

    link_files appends `- [[id]]` to the end of the body, so those lines land inside
    whatever the last heading happens to span. Extracting that last section then
    carries the file's links away with it -- observed for real: splitting the tail
    off a file moved two of its links to the new file and left both targets with a
    one-sided link. The links belong to the file, not to whichever section happens
    to be last, so they stay behind.
    """
    if end != len(lines):
        return end
    i = end
    while i > start and (lines[i - 1].strip() == "" or _LINK_LINE_RE.match(lines[i - 1].strip())):
        i -= 1
    has_link = any(_LINK_LINE_RE.match(line.strip()) for line in lines[i:end])
    return i if has_link else end


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
    end = _end_excluding_file_links(lines, start, end)
    extracted = "\n".join(lines[start:end]).strip("\n")
    remaining = "\n".join(lines[:start] + lines[end:])
    return extracted, remaining


def extract_sections(body: str, headings: list[str]) -> tuple[str, str] | None:
    """Remove several named sections at once. Returns (extracted_text, remaining_body),
    or None if any heading is missing.

    Splitting one section at a time cannot express "these three related sections
    belong together in one file" -- the case that actually arises, since a theme
    worth splitting out usually accumulated across several appends rather than in a
    single heading. Extracted text keeps document order regardless of the order the
    headings are named in, so the result reads the way it did in the source.

    All-or-nothing on a missing heading: a partial extraction would cut the file
    along seams the caller did not choose and leave no obvious trace of which ones.
    """
    bounds: list[tuple[int, int]] = []
    for heading in headings:
        found = find_section_bounds(body, heading)
        if found is None:
            return None
        bounds.append(found)

    bounds.sort()
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:]):
        if next_start < prev_end:
            raise ValidationError(
                "requested sections overlap (one is nested inside another); "
                "extract the outer section on its own"
            )

    lines = body.splitlines()
    last_start, last_end = bounds[-1]
    bounds[-1] = (last_start, _end_excluding_file_links(lines, last_start, last_end))

    extracted = "\n\n".join("\n".join(lines[s:e]).strip("\n") for s, e in bounds)
    remaining: list[str] = []
    prev = 0
    for start, end in bounds:
        remaining.extend(lines[prev:start])
        prev = end
    remaining.extend(lines[prev:])
    return extracted, "\n".join(remaining)
