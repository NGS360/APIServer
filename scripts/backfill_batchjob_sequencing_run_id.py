#!/usr/bin/env python3
"""
Attribute historical batch jobs to the sequencing run named in their job name.

Companion to migration a3c81f0d5e29, which adds batchjob.sequencing_run_id but
writes no data: jobs submitted since then get the run from the submission path,
so only older rows need this. It is out here rather than in the migration
because a run id has no fixed shape, so the only way to recognise one is to
match against the run table itself -- unindexable in SQL, and slow enough that
in-migration it would stall container startup and risk a health-check timeout.
Here it runs against a prefix index instead.

Job names are not guaranteed to carry a run id -- demux names come from
operator-authored YAML in S3 -- so anything that resolves to no run, or to more
than one, is left NULL and reported rather than guessed at (--show-ambiguous).

Safe against a live database: restartable (only rows still NULL are considered),
chunked so no lock is held for long, and --dry-run writes nothing. The target is
whatever SQLALCHEMY_DATABASE_URI points at, so run it once per tier; the tier and
database are echoed back and must be confirmed unless --yes is given.

Usage:
    PYTHONPATH=. python3 scripts/backfill_batchjob_sequencing_run_id.py --dry-run
    PYTHONPATH=. python3 scripts/backfill_batchjob_sequencing_run_id.py
"""

import argparse
import logging
import sys
import time
from collections import defaultdict

from sqlalchemy import text
from sqlmodel import Session, col, select

sys.path.insert(0, ".")

from api.jobs.models import BatchJob  # noqa: E402
from api.runs.models import SequencingRun  # noqa: E402
# SequencingRun.qcrecords relates to QCRecord by name, and QCRecord in turn
# relates to Project and Sample, so none of the mappers can be configured until
# the whole cluster has been imported. Same reason, and same import set, as
# reindex.py.
from api.project.models import Project  # noqa: E402,F401
from api.qcmetrics.models import QCMetric, QCRecord  # noqa: E402,F401
from api.samples.models import Sample  # noqa: E402,F401
from core.config import get_settings  # noqa: E402
from core.db import engine  # noqa: E402

from scripts.create_service_account import _mask_uri, confirm_target  # noqa: E402

logger = logging.getLogger("backfill_batchjob_sequencing_run_id")

# Length of the run-id prefix used to index candidate positions in a job name.
# Any occurrence of run_id inside name starts with run_id's first PREFIX_LEN
# characters, so indexing on that prefix and confirming the full substring is
# exactly equivalent to `name LIKE CONCAT('%', run_id, '%')` -- just without
# comparing every job against every run. Eight is comfortably inside the date
# prefix both instrument families start with, so it partitions the run table
# finely while staying shorter than any real run id.
PREFIX_LEN = 8


class RunMatcher:
    """Finds which sequencing runs a job name names, by exact substring match."""

    def __init__(self, run_ids: list[str]) -> None:
        self._by_prefix: dict[str, list[str]] = defaultdict(list)
        # Run ids shorter than the prefix cannot be indexed this way. None are
        # expected -- the column is 255 wide and real ids are 20-40 characters --
        # but a truncated or hand-entered row should not be silently skipped.
        self._short: list[str] = []
        for run_id in run_ids:
            if len(run_id) >= PREFIX_LEN:
                self._by_prefix[run_id[:PREFIX_LEN]].append(run_id)
            else:
                self._short.append(run_id)

    def matches(self, name: str) -> set[str]:
        """Every run id that occurs as a substring of `name`."""
        found = {run_id for run_id in self._short if run_id and run_id in name}
        for i in range(len(name) - PREFIX_LEN + 1):
            for run_id in self._by_prefix.get(name[i:i + PREFIX_LEN], ()):
                if name.startswith(run_id, i):
                    found.add(run_id)
        return found


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change and write nothing")
    ap.add_argument("--all", action="store_true",
                    help="Re-evaluate every job, not only those with no run yet. "
                         "Never clears a value; only overwrites when a name now "
                         "resolves to a different run.")
    ap.add_argument("--chunk-size", type=int, default=500,
                    help="Rows per transaction (default 500). Smaller means "
                         "shorter locks against a live database.")
    ap.add_argument("--show-ambiguous", action="store_true",
                    help="List the jobs whose name matched more than one run "
                         "instead of only counting them")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="Skip the tier confirmation prompt")
    args = ap.parse_args()

    if args.chunk_size < 1:
        ap.error("--chunk-size must be at least 1")

    settings = get_settings()
    print(f"tier:     {settings.ENVIRONMENT}")
    print(f"database: {_mask_uri(settings.SQLALCHEMY_DATABASE_URI)}")
    print()

    with Session(engine) as session:
        run_ids = [r for r in session.exec(select(SequencingRun.run_id)).all() if r]
        matcher = RunMatcher(run_ids)

        jobs_query = select(BatchJob.id, BatchJob.name)
        if not args.all:
            jobs_query = jobs_query.where(col(BatchJob.sequencing_run_id).is_(None))
        jobs = session.exec(jobs_query).all()

        print(f"runs:     {len(run_ids)}")
        print(f"jobs:     {len(jobs)} "
              f"({'all' if args.all else 'with no run attributed yet'})")
        print()

        started = time.monotonic()
        resolved: list[dict[str, str]] = []
        ambiguous: list[tuple[str, str, set[str]]] = []
        for job_id, name in jobs:
            if not name:
                continue
            found = matcher.matches(name)
            if len(found) == 1:
                resolved.append({"jid": job_id, "rid": next(iter(found))})
            elif len(found) > 1:
                ambiguous.append((job_id, name, found))
        elapsed = time.monotonic() - started

        unresolved = len(jobs) - len(resolved) - len(ambiguous)
        print(f"matched in {elapsed:.1f}s:")
        print(f"  resolve to exactly one run: {len(resolved)}")
        print(f"  match more than one run:    {len(ambiguous)} (skipped)")
        print(f"  match no run:               {unresolved} (left NULL)")
        print()

        if ambiguous and args.show_ambiguous:
            print("ambiguous jobs (not written):")
            for job_id, name, found in ambiguous:
                print(f"  {job_id}  {name}  -> {sorted(found)}")
            print()

        if not resolved:
            print("nothing to write")
            return 0

        if args.dry_run:
            print(f"--dry-run: would set sequencing_run_id on {len(resolved)} jobs")
            return 0

        confirm_target(
            settings,
            f"set sequencing_run_id on {len(resolved)} batchjob rows",
            args.yes,
        )

        # Keyed on the primary key rather than re-running the match in SQL, so
        # each statement touches one indexed row and the chunk commits quickly.
        stmt = text("UPDATE batchjob SET sequencing_run_id = :rid WHERE id = :jid")

        written = 0
        for start in range(0, len(resolved), args.chunk_size):
            chunk = resolved[start:start + args.chunk_size]
            # executemany over the chunk, then commit, so locks are released
            # every chunk-size rows instead of held for the whole backfill.
            session.connection().execute(stmt, chunk)
            session.commit()
            written += len(chunk)
            print(f"  committed {written}/{len(resolved)}", end="\r", flush=True)

        print(f"  committed {written}/{len(resolved)}")
        print()
        print(f"done: sequencing_run_id set on {written} batchjob rows")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
