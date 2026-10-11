"""Extract exact source-backed support-table rows as verification CANDIDATES.

No online facts, versions or dates are hardcoded. A yes/no matrix is parsed
only from an anchored, publisher-named support policy on a public HTTPS URL.
The existing model verifier must still accept each generated atomic claim.
"""
import re
from urllib.parse import urlsplit

from agent.research_followup import support_policy_question

# Trusted canonical publisher hosts. Unknown projects keep the ordinary
# extraction/verification path; no cross-domain authority is inferred from
# matching a project name to a lookalike hostname.
_OFFICIAL_POLICY_HOSTS = {"postgresql": "postgresql.org"}
_HEADER = re.compile(r"(?i)^\s*versions?\s*\|")
_NAME = re.compile(r"^[0-9]{1,2}(?:\.[0-9])?$")
_STATUS_YES = re.compile(r"^(?:yes|ja|supported|active)$", re.I)
_STATUS_NO = re.compile(r"^(?:no|nein|unsupported|eol|inactive)$", re.I)


def _publisher_name(goal, url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.lower().rstrip(".")
        if not re.search(r"/(?:support|versioning|versions|lifecycle)(?:/|$)", parts.path, re.I):
            return None
        if host.startswith("www."):
            host = host[4:]
        labels = host.split(".")
        # Conservative canonical apex domain. A project-name prefix on a
        # longer attacker-controlled hostname must never grant authority.
        if len(labels) != 2:
            return None
        stem = labels[0]
        if _OFFICIAL_POLICY_HOSTS.get(stem) != host:
            return None
        # A matching named publisher and its actual source URL are required;
        # even a different subdomain or a lookalike suffix is not promoted.
        match = re.search(r"(?<!\w)" + re.escape(stem) + r"(?!\w)", goal, re.I)
        return goal[match.start():match.end()] if match else None
    except ValueError:
        return None


def support_matrix_candidates(goal, bundle, *, limit=8):
    """Return (subject, statement, anchored_passage_id) for clear Yes rows.

    Any duplicate version with contradictory labels is excluded, and rows
    are never spliced across distinct sources. This is not model verification.
    """
    if not support_policy_question(goal):
        return []
    versions = {}
    for source in bundle.sources:
        publisher = _publisher_name(str(goal), source.final_url)
        if not publisher or source.retrieval_status != "loaded":
            continue
        for fact in bundle.facts:
            if fact.source_id != source.id or "-support-" not in fact.id:
                continue
            lines = fact.evidence_excerpt.splitlines()
            for start, line in enumerate(lines):
                # The HTML extractor emits a leading " | " before the
                # first <th>/<td>. Strip only framing delimiters, never
                # cell content or line breaks between status rows.
                header = line.strip(" |")
                if not _HEADER.match(header):
                    continue
                columns = [part.strip().lower() for part in header.split("|")]
                if not columns or columns[0] not in {"version", "versions"}:
                    continue
                supported = next(
                    (i for i, col in enumerate(columns) if col in {"supported", "support status"}),
                    None,
                )
                if supported is None:
                    continue
                for row in lines[start + 1:]:
                    # HTML extraction retains paragraph/row separation as
                    # blank lines. Ignore ONLY whitespace separators: never
                    # skip unrelated text or malformed table rows.
                    if not row.strip():
                        continue
                    values = [value.strip() for value in row.strip(" |").split("|")]
                    if len(values) != len(columns) or not _NAME.fullmatch(values[0]):
                        break
                    status = values[supported]
                    if not _STATUS_YES.fullmatch(status) and not _STATUS_NO.fullmatch(status):
                        break
                    version = values[0]
                    key = publisher.casefold() + "/" + version
                    item = (publisher, version, status.casefold(), fact.id)
                    if key in versions:
                        if versions[key] is not None and versions[key][2] != item[2]:
                            versions[key] = None
                    else:
                        versions[key] = item
                break
    records = []
    for item in versions.values():
        if not item or not _STATUS_YES.fullmatch(item[2]):
            continue
        publisher, version, _, fact_id = item
        statement = (f"{publisher} {version} ist in der offiziellen "
                     "Versionsrichtlinie als unterstützt gekennzeichnet.")
        records.append((f"{publisher} {version}", statement, fact_id))
        if len(records) >= max(0, min(8, limit)):
            break
    return records


# These terms select additional potentially contradictory or qualifying claims;
# they never establish that any version is supported.
_POLICY_CONFLICT_CUE = re.compile(
    r"(?i)\\b(?:support(?:ed|s|ing)?|unsupported|unterstützt\\w*|"
    r"end[- ]of[- ]life|eol|retir(?:ed|ement)|obsolete|deprecated|"
    r"discontinued|maintain(?:ed|ance)?|ausgelaufen|veraltet)\\b"
)


def support_matrix_verification_scope(goal, bundle, rows):
    """Limit table verification to evidence relevant to version support.

    Every anchored support matrix from the *same named official publisher*
    remains in scope, together with prose discussing support and every mention
    of a candidate version from the official policy. Other retrieved pages
    contribute potentially conflicting, version-specific statements.

    This narrows the verifier's prompt, not its authority: selected evidence
    remains byte-for-byte anchored and the ordinary LLM verifier still checks
    every candidate. If attribution fails, retain the full-context behavior.
    """
    if not rows or not support_policy_question(goal):
        return None
    official_ids = {
        source.id for source in bundle.sources
        if source.retrieval_status == "loaded"
        and _publisher_name(str(goal), source.final_url)
    }
    anchor_ids = {pid for _, _, pid in rows}
    available = {fact.id for fact in bundle.facts}
    if not official_ids or not anchor_ids.issubset(available):
        return None
    version_names = [subject.rsplit(" ", 1)[-1] for subject, _, _ in rows]
    if any(not _NAME.fullmatch(name) for name in version_names):
        return None
    version_terms = [re.compile(r"(?<![\\w.])" + re.escape(name) + r"(?![\\w.])")
                     for name in version_names]

    relevant = set(anchor_ids)
    for fact in bundle.facts:
        excerpt = fact.evidence_excerpt
        named_version = any(term.search(excerpt) for term in version_terms)
        policy_source = fact.source_id in official_ids
        # Includes conflicting Yes/No rows in other policy windows, even if
        # the candidate versions are not mentioned in their first row.
        if policy_source and "-support-" in fact.id:
            relevant.add(fact.id)
        elif policy_source and (named_version or _POLICY_CONFLICT_CUE.search(excerpt)):
            relevant.add(fact.id)
        elif named_version and _POLICY_CONFLICT_CUE.search(excerpt):
            relevant.add(fact.id)

    if not anchor_ids.issubset(relevant):
        return None
    # Same bounded cross-source evidence is visible to every table claim;
    # a contradictory status for one version must never be hidden by splitting
    # the input into isolated per-version windows.
    return {"c-" + str(i): tuple(sorted(relevant))
            for i, _ in enumerate(rows, 1)}
