"""Read-only whole-store audit (spec §5 size pressure, §12 links, §14 index).

Every integrity guarantee in this package is enforced at *write* time: link_files
self-checks bidirectionality before returning, create_file upserts the index entry
in the same call. Nothing ever re-examined the store as a whole afterwards, so
anything that drifted stayed invisible -- a hand-edited file, a link written before
that self-check existed, an index entry left behind by a file that moved, or a file
that grew past a §5 threshold and then simply stopped being appended to.

That last case is why this exists alongside the `attention` field on writes: that
signal only fires on the write that crosses the line, so a file already sitting at
1126 lines never announces itself again. This is the sweep that answers "what needs
attention" without waiting for someone to touch the right file.

Reporting only -- nothing here mutates or decides. Acting on any of it (split,
summarize, archive, relink) stays with the caller, per §11/§17.
"""
from __future__ import annotations

from pathlib import Path

from . import models
from .index import read_index
from .linkgraph import extract_links, extract_structural_links
from .store import load_all


def check_health(root: Path) -> dict:
    files = load_all(root)
    by_id = {mf.id: mf for mf in files}
    live = [mf for mf in files if not mf.is_archived]

    # §5: files already past a threshold, which the write-time nudge cannot reach.
    oversized = []
    for mf in live:
        attention = models.size_attention(mf.body)
        if attention:
            oversized.append(
                {
                    "id": mf.id,
                    "line_count": models.line_count(mf.body),
                    "size_level": models.size_level(mf.body),
                    "attention": attention,
                }
            )
    oversized.sort(key=lambda d: -d["line_count"])

    # §12: the two halves of a link, exactly as link_files defines them.
    forward = {mf.id: extract_structural_links(mf.body) for mf in files}
    mentions = {mf.id: extract_links(mf.body) for mf in files}
    parents = {mf.id: list(mf.fm.get("parent") or []) for mf in files}

    one_sided: list[dict] = []
    broken: list[dict] = []
    for src in sorted(forward):
        for tgt in forward[src]:
            if tgt not in by_id:
                broken.append({"from": src, "to": tgt, "kind": "reference"})
            elif src not in parents[tgt]:
                one_sided.append(
                    {"from": src, "to": tgt, "has_forward": True, "has_backward": False}
                )
    for child in sorted(parents):
        for parent in parents[child]:
            if parent not in by_id:
                broken.append({"from": child, "to": parent, "kind": "parent"})
            elif child not in forward[parent]:
                # link_files once used the broad extract_links and so skipped writing
                # the real `- [[id]]` line whenever a prose mention already existed.
                # The code was fixed; files written before that were not. Saying which
                # shape this is matters, because the repair differs: promote the prose
                # mention to a structural line, versus create the link outright.
                one_sided.append(
                    {
                        "from": parent,
                        "to": child,
                        "has_forward": False,
                        "has_backward": True,
                        "prose_mention_only": child in mentions[parent],
                    }
                )

    # A file nothing points at and that points at nothing is unreachable by §15's
    # hop expansion -- findable only if a keyword happens to hit it.
    referenced: set[str] = set()
    for targets in forward.values():
        referenced.update(targets)
    for ps in parents.values():
        referenced.update(ps)
    orphans = sorted(
        mf.id
        for mf in live
        if not forward[mf.id] and not parents[mf.id] and mf.id not in referenced
    )

    # §14: index.md is the registry; disk is the truth.
    indexed = {e.id for e in read_index(root)}
    on_disk = set(by_id)

    return {
        "oversized": oversized,
        "orphans": orphans,
        "index_missing_entry": sorted(on_disk - indexed),
        "index_stale_entry": sorted(indexed - on_disk),
        "one_sided_links": one_sided,
        "broken_links": broken,
        "checked_file_count": len(files),
    }
