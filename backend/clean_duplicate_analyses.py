"""
Maintenance: clean historical duplicate extraction rows
=======================================================
Every upload today is de-duplicated before extraction: the pipeline
hashes each file (`content_sha256`) and refuses a file the workspace has
already stored. Rows written before that guard existed — or by a
reprocess that was interrupted between the delete and the re-insert —
can still leave a workspace holding the SAME extracted page twice.

A duplicated page row is not a cosmetic problem. Every medication on it
appears under a second (date, source_file) pair, which is exactly the
shape the duplicate-prescription and cross-check logic reads as "this
drug was prescribed more than once", and it inflates the counts shown in
the AI analysis log. That is a false alarm manufactured by ingestion, not
a fact about the patient.

WHAT THIS DELETES (and what it will never touch)
------------------------------------------------
Only rows that are byte-for-byte the same extraction of the same page of
the same physical upload:

  * same upload identity (content hash / storage id / filename — the same
    precedence db.delete_document_group uses),
  * same page number,
  * identical extracted clinical payload, compared after stripping the
    per-row bookkeeping fields (`_document_id`, storage URLs, upload
    timestamps) that legitimately differ between two ingests of one page.

The NEWEST row of each such set is kept. Everything else is preserved:

  * pages of a multi-page document (different page numbers) — never
    duplicates of each other,
  * two extractions of the same page whose clinical content differs at
    all (a reprocess that read the page better is real new information;
    resolving it belongs to the conflict workflow, not to a cleanup),
  * any row whose document id has correction events attached, so an
    audited human correction can never be orphaned,
  * rows with no usable identity, which are reported as "unmapped" and
    left alone,
  * snapshots, corrections, conflicts, conversations and every other
    derived table — this script only ever deletes `documents` rows.

Dry run is the default: nothing is deleted without `--execute`.

Usage:
    python clean_duplicate_analyses.py --user-id <uuid>            # report
    python clean_duplicate_analyses.py --user-id <uuid> --execute  # delete
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from analysis_log import upload_group_key

logger = logging.getLogger("maintenance.duplicates")

# Fields that describe HOW/WHEN a page row was stored rather than what the
# document says. Two ingests of one page differ here by construction, so
# they are excluded before the clinical payloads are compared.
_BOOKKEEPING_FIELDS = frozenset(
    {
        "_document_id",
        "uploaded_at",
        "user_id",
        "document_url",
        "cloudinary_public_id",
        "storage_backend",
        "storage_path",
        "storage_bucket",
        "raw_text_processing",
    }
)


def _payload_fingerprint(data: Dict[str, Any]) -> str:
    """Stable hash of the clinical content of one extracted page row."""
    payload = {key: value for key, value in sorted(data.items()) if key not in _BOOKKEEPING_FIELDS}
    try:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return ""
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _page_number(data: Dict[str, Any]) -> int:
    source = data.get("_source") if isinstance(data.get("_source"), dict) else {}
    try:
        return int(source.get("page") or 1)
    except (TypeError, ValueError):
        return 1


def _has_identity(data: Dict[str, Any]) -> bool:
    """True when the row can be tied to a physical upload.

    A row with no hash, no storage id and no filename cannot be proven to
    be the same upload as another row, so it is never a deletion
    candidate.
    """
    identity_fields = ("content_sha256", "cloudinary_public_id", "storage_path")
    if any(str(data.get(field) or "").strip() for field in identity_fields):
        return True
    source = data.get("_source") if isinstance(data.get("_source"), dict) else {}
    return bool(str(source.get("file") or "").strip())


def _sort_key(row: Dict[str, Any]) -> Tuple[str, str]:
    return (str(row.get("uploaded_at") or ""), str(row.get("id") or ""))


def plan_duplicate_cleanup(
    rows: Sequence[Dict[str, Any]],
    *,
    corrected_document_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Decide which document rows are exact duplicates of a kept row.

    `rows` are raw storage rows: {"id", "uploaded_at", "data"}. Returns a
    plan describing what would be deleted; it never touches a database, so
    the caller decides whether to execute it.
    """
    protected: Set[str] = {str(value) for value in (corrected_document_ids or []) if value}

    groups: Dict[Tuple[str, int, str], List[Dict[str, Any]]] = {}
    unmapped: List[Dict[str, Any]] = []

    for row in rows or []:
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if not data or not _has_identity(data):
            unmapped.append(row)
            continue
        fingerprint = _payload_fingerprint(data)
        if not fingerprint:
            unmapped.append(row)
            continue
        key = (upload_group_key(data), _page_number(data), fingerprint)
        groups.setdefault(key, []).append(row)

    duplicates: List[Dict[str, Any]] = []
    kept = 0
    preserved_corrected = 0

    for group in groups.values():
        # Newest first: the most recent ingest of a page is the one the
        # rest of the record (snapshot, index, corrections) refers to.
        ordered = sorted(group, key=_sort_key, reverse=True)
        kept += 1
        for row in ordered[1:]:
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            document_id = str(data.get("_document_id") or "")
            if document_id and document_id in protected:
                preserved_corrected += 1
                kept += 1
                continue
            duplicates.append(
                {
                    "id": row.get("id"),
                    "document_id": document_id,
                    "source_file": (
                        (data.get("_source") or {}).get("file")
                        if isinstance(data.get("_source"), dict)
                        else None
                    ),
                    "page": _page_number(data),
                    "uploaded_at": row.get("uploaded_at"),
                }
            )

    return {
        "total_scanned": len(rows or []),
        "unique_groups": len(groups),
        "kept_records": kept + len(unmapped),
        "duplicates_identified": len(duplicates),
        "duplicates": duplicates,
        "unmapped_preserved": len(unmapped),
        "corrected_preserved": preserved_corrected,
    }


def clean_duplicate_document_rows(
    user_id: str,
    *,
    dry_run: bool = True,
    db_module: Any = None,
) -> Dict[str, Any]:
    """Report (and optionally delete) exact duplicate page rows for a user.

    Deletion is user-scoped: every read and write goes through the same
    user_id, so this can never reach another workspace's records.
    """
    if db_module is None:  # pragma: no cover - import kept local for tests
        import db as db_module  # type: ignore[no-redef]

    rows = db_module.load_document_rows(user_id)
    try:
        corrected_ids = [
            str(event.get("document_id"))
            for event in db_module.load_correction_events(user_id)
            if event.get("document_id")
        ]
    except Exception as exc:  # a missing corrections table must not delete more
        logger.warning("correction events unavailable, protecting nothing extra: %s", exc)
        corrected_ids = []

    plan = plan_duplicate_cleanup(rows, corrected_document_ids=corrected_ids)

    deleted = 0
    if not dry_run and plan["duplicates"]:
        deleted = db_module.delete_document_rows(
            user_id, [item["id"] for item in plan["duplicates"]]
        )

    summary = {
        "user_id": user_id,
        "dry_run": dry_run,
        "records_deleted": deleted,
        **{key: value for key, value in plan.items() if key != "duplicates"},
    }
    logger.info("duplicate document cleanup (dry_run=%s): %s", dry_run, summary)
    summary["duplicates"] = plan["duplicates"]
    return summary


def main() -> None:  # pragma: no cover - CLI entry point
    parser = argparse.ArgumentParser(
        description="Report or remove exact duplicate extracted document rows for one workspace.",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="Workspace/user id to clean. Every query is scoped to this user.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete the duplicates (default: dry-run report only).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    import db

    summary = clean_duplicate_document_rows(args.user_id, dry_run=not args.execute, db_module=db)
    for item in summary["duplicates"]:
        print(
            f"  duplicate row id={item['id']} page={item['page']} "
            f"file={item['source_file']} document_id={item['document_id']}"
        )
    print(
        "Cleanup {}: scanned={} groups={} duplicates={} deleted={} kept={} "
        "unmapped_preserved={} corrected_preserved={}".format(
            "DRY RUN" if summary["dry_run"] else "COMPLETE",
            summary["total_scanned"],
            summary["unique_groups"],
            summary["duplicates_identified"],
            summary["records_deleted"],
            summary["kept_records"],
            summary["unmapped_preserved"],
            summary["corrected_preserved"],
        )
    )
    if summary["dry_run"] and summary["duplicates_identified"]:
        print("Re-run with --execute to delete the rows listed above.")


if __name__ == "__main__":  # pragma: no cover
    main()
