#!/usr/bin/env python
"""Collapse attribute rows whose keys differ only by capitalization.

Entity attributes are stored one-row-per-key in tables such as
``sampleattribute`` with a ``UniqueConstraint(entity_id, key)``. That
constraint is only case-insensitive when the ``key`` column carries a
case-insensitive collation. On any deployment where it does not (or for legacy
rows imported before the app-level dedup existed) the same logical key can be
stored twice differing only in case, e.g. ``SOURCE_URI`` and ``source_uri``.
There is never a case where the two casings should hold different values.

This script finds every ``(entity_id, lower(key))`` group with more than one
row and, per group:

  * **Values identical** -> keep a single row (preferring the casing already most
    common for that key across the table, else the first row) and delete the
    rest. Counted as ``merged``.
  * **Values differ** -> leave every row untouched and record the group in a
    conflicts report for manual resolution. Counted as ``conflicts``. The
    attribute tables carry no timestamp, so "most recent wins" is not knowable.

Run this BEFORE applying the migration that enforces a case-insensitive unique
constraint — that migration will fail while duplicates remain.

Usage:
    PYTHONPATH=. python3 scripts/dedupe_attribute_case.py [--dry-run] \
        [--entity {sample,project,pipeline,workflow,workflowversion,filetag,all}]

``--dry-run`` is the default: nothing is written unless you pass
``--no-dry-run``. Work is committed per table; a failure in one table rolls that
table back and the script continues with the next.
"""
import sys
from collections import Counter, defaultdict

from sqlmodel import select

from core.db import get_session
from core.logger import logger

# Import all models first to ensure proper SQLAlchemy relationship resolution.
from api.project.models import Project, ProjectAttribute  # noqa: F401
from api.runs.models import SequencingRun  # noqa: F401
from api.files.models import File, FileSample, FileTag  # noqa: F401
from api.samples.models import Sample, SampleAttribute  # noqa: F401
from api.pipeline.models import Pipeline, PipelineAttribute  # noqa: F401
from api.workflow.models import (  # noqa: F401
    Workflow,
    WorkflowAttribute,
    WorkflowVersion,
    WorkflowVersionAttribute,
)


# name -> (model class, parent-id attribute name). ``key``/``value`` columns are
# assumed on every attribute table.
ATTRIBUTE_TABLES = {
    "sample": (SampleAttribute, "sample_id"),
    "project": (ProjectAttribute, "project_id"),
    "pipeline": (PipelineAttribute, "pipeline_id"),
    "workflow": (WorkflowAttribute, "workflow_id"),
    "workflowversion": (WorkflowVersionAttribute, "workflow_version_id"),
    "filetag": (FileTag, "file_id"),
}


def _empty_stats() -> dict:
    return {"groups": 0, "merged": 0, "conflicts": 0}


def _pick_survivor(rows: list) -> object:
    """Choose which row to keep among identical-valued duplicates.

    Prefers the casing already most common for this key across the group; ties
    (and single-row-per-casing groups) fall back to the first row, giving a
    stable, deterministic result.
    """
    casing_counts = Counter(r.key for r in rows)
    best_key, _ = max(
        casing_counts.items(), key=lambda kv: (kv[1], kv[0])
    )
    for r in rows:
        if r.key == best_key:
            return r
    return rows[0]


def dedupe_table(
    session,
    model,
    parent_attr: str,
    dry_run: bool = True,
) -> tuple[dict, list[dict]]:
    """Collapse case-only duplicate keys in a single attribute table.

    Groups rows by ``(parent_id, lower(key))``. Identical-value groups are
    merged to one row; differing-value groups are reported, not touched.
    Commits once (unless ``dry_run``) after the whole table is processed; on
    error the table's changes are rolled back and the exception re-raised.

    Returns ``(stats, conflicts)`` where ``stats`` counts groups/merged/
    conflicts and ``conflicts`` is a list of report dicts for manual review.
    """
    table_name = model.__tablename__
    parent_col = getattr(model, parent_attr)

    rows = session.exec(select(model)).all()

    # Group by (parent_id, lowered key)
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        parent_id = getattr(row, parent_attr)
        groups[(parent_id, row.key.lower())].append(row)

    stats = _empty_stats()
    conflicts: list[dict] = []

    try:
        for (parent_id, lowered), grouped in groups.items():
            if len(grouped) < 2:
                continue

            stats["groups"] += 1
            distinct_values = {r.value for r in grouped}

            if len(distinct_values) > 1:
                # Values disagree — do not guess. Report for manual fixing.
                stats["conflicts"] += 1
                conflict = {
                    "table": table_name,
                    parent_attr: str(parent_id),
                    "key_lower": lowered,
                    "variants": [
                        {"key": r.key, "value": r.value} for r in grouped
                    ],
                }
                conflicts.append(conflict)
                logger.warning(
                    "CONFLICT %s %s=%s key~%r has differing values: %s",
                    table_name, parent_attr, parent_id, lowered,
                    ", ".join(f"{r.key}={r.value!r}" for r in grouped),
                )
                continue

            # All values identical — keep one, delete the rest.
            survivor = _pick_survivor(grouped)
            losers = [r for r in grouped if r.id != survivor.id]
            stats["merged"] += 1

            if dry_run:
                logger.info(
                    "[DRY RUN] %s %s=%s: keep key=%r, drop %s",
                    table_name, parent_attr, parent_id, survivor.key,
                    [r.key for r in losers],
                )
            else:
                for r in losers:
                    session.delete(r)

        if not dry_run:
            session.commit()
    except Exception:
        session.rollback()
        raise

    logger.info(
        "%s%s: %d duplicate group(s) — %d merged, %d conflict(s) reported",
        "[DRY RUN] " if dry_run else "",
        table_name, stats["groups"], stats["merged"], stats["conflicts"],
    )
    return stats, conflicts


def dedupe_attributes(
    session,
    entity: str = "all",
    dry_run: bool = True,
) -> tuple[dict, list[dict]]:
    """Run the dedupe across one or all attribute tables, committing per table.

    Returns aggregate ``(stats, conflicts)``; ``stats`` also carries
    ``tables_processed`` and a ``failed_tables`` list.
    """
    if entity == "all":
        selected = list(ATTRIBUTE_TABLES)
    else:
        selected = [entity]

    logger.info("Deduping case-only attribute keys across: %s", ", ".join(selected))

    total = _empty_stats()
    all_conflicts: list[dict] = []
    failed: list[str] = []

    for name in selected:
        model, parent_attr = ATTRIBUTE_TABLES[name]
        try:
            stats, conflicts = dedupe_table(
                session, model, parent_attr, dry_run=dry_run
            )
            for k, v in stats.items():
                total[k] += v
            all_conflicts.extend(conflicts)
        except Exception as exc:  # noqa: BLE001 — keep going across tables
            logger.error("Table %s failed and was rolled back: %s", name, exc)
            failed.append(name)

    total["tables_processed"] = len(selected)
    total["failed_tables"] = failed
    return total, all_conflicts


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Collapse attribute rows whose keys differ only by capitalization."
        )
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Log intended changes without writing (default).",
    )
    parser.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_false",
        help="Actually delete duplicate rows.",
    )
    parser.add_argument(
        "--entity",
        choices=list(ATTRIBUTE_TABLES) + ["all"],
        default="all",
        help="Which attribute table(s) to process (default: all).",
    )
    return parser.parse_args()


def _print_conflicts(conflicts: list[dict]) -> None:
    if not conflicts:
        return
    logger.error(
        "%d conflict group(s) left untouched — resolve these manually:",
        len(conflicts),
    )
    for c in conflicts:
        parent_key = next(
            k for k in c if k not in ("table", "key_lower", "variants")
        )
        variants = "; ".join(
            f"{v['key']}={v['value']!r}" for v in c["variants"]
        )
        logger.error(
            "  %s %s=%s key~%r: %s",
            c["table"], parent_key, c[parent_key], c["key_lower"], variants,
        )


if __name__ == "__main__":
    args = parse_args()

    session = next(get_session())
    if not session:
        logger.error("Database session could not be created.")
        sys.exit(-1)

    stats, conflicts = dedupe_attributes(
        session, entity=args.entity, dry_run=args.dry_run
    )

    logger.info(
        "%sDedupe complete across %d table(s): "
        "%d duplicate group(s), %d merged, %d conflict(s)",
        "[DRY RUN] " if args.dry_run else "",
        stats["tables_processed"], stats["groups"],
        stats["merged"], stats["conflicts"],
    )
    _print_conflicts(conflicts)

    if stats["failed_tables"]:
        logger.error(
            "%d table(s) failed and were rolled back: %s",
            len(stats["failed_tables"]), ", ".join(stats["failed_tables"]),
        )
        sys.exit(1)

    if conflicts:
        # Non-zero exit so CI/operators notice unresolved conflicts.
        sys.exit(2)
