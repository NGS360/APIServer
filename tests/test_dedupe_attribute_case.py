"""Unit tests for scripts/dedupe_attribute_case.py.

The test DB is SQLite, whose unique constraint is case-sensitive, so
case-only duplicate rows can be inserted directly — exactly the situation the
dedupe script exists to clean up.
"""
import uuid

from sqlmodel import Session, select

from api.samples.models import SampleAttribute
from scripts.dedupe_attribute_case import (
    dedupe_table,
    dedupe_attributes,
)


def _add_attr(session: Session, sample_id: uuid.UUID, key: str, value: str):
    session.add(SampleAttribute(sample_id=sample_id, key=key, value=value))


def test_merges_identical_value_duplicates(session: Session):
    """Case-only duplicates with identical values collapse to one row."""
    sid = uuid.uuid4()
    _add_attr(session, sid, "SOURCE_URI", "s3://bucket/x")
    _add_attr(session, sid, "source_uri", "s3://bucket/x")
    _add_attr(session, sid, "organism", "Homo sapiens")  # untouched control
    session.commit()

    stats, conflicts = dedupe_table(
        session, SampleAttribute, "sample_id", dry_run=False
    )

    assert stats["merged"] == 1
    assert stats["conflicts"] == 0
    assert conflicts == []

    remaining = session.exec(
        select(SampleAttribute).where(SampleAttribute.sample_id == sid)
    ).all()
    # One SOURCE_URI/source_uri row survives + the untouched organism row.
    assert len(remaining) == 2
    keys_lower = sorted(a.key.lower() for a in remaining)
    assert keys_lower == ["organism", "source_uri"]


def test_reports_conflicting_values_without_deleting(session: Session):
    """Case-only duplicates with differing values are reported, not modified."""
    sid = uuid.uuid4()
    _add_attr(session, sid, "SOURCE_URI", "s3://bucket/x")
    _add_attr(session, sid, "source_uri", "s3://bucket/y")
    session.commit()

    stats, conflicts = dedupe_table(
        session, SampleAttribute, "sample_id", dry_run=False
    )

    assert stats["merged"] == 0
    assert stats["conflicts"] == 1
    assert len(conflicts) == 1
    assert conflicts[0]["key_lower"] == "source_uri"
    assert {v["value"] for v in conflicts[0]["variants"]} == {
        "s3://bucket/x",
        "s3://bucket/y",
    }

    # Both rows must remain — the script never guesses which value wins.
    remaining = session.exec(
        select(SampleAttribute).where(SampleAttribute.sample_id == sid)
    ).all()
    assert len(remaining) == 2


def test_dry_run_makes_no_changes(session: Session):
    """--dry-run counts the merge but leaves rows in place."""
    sid = uuid.uuid4()
    _add_attr(session, sid, "TISSUE", "liver")
    _add_attr(session, sid, "tissue", "liver")
    session.commit()

    stats, _ = dedupe_table(
        session, SampleAttribute, "sample_id", dry_run=True
    )

    assert stats["merged"] == 1
    remaining = session.exec(
        select(SampleAttribute).where(SampleAttribute.sample_id == sid)
    ).all()
    assert len(remaining) == 2  # nothing deleted


def test_dedupe_attributes_aggregates_and_reports(session: Session):
    """dedupe_attributes rolls up per-table stats and conflict lists."""
    sid = uuid.uuid4()
    _add_attr(session, sid, "ASSAY", "wgs")
    _add_attr(session, sid, "assay", "wgs")          # merged
    _add_attr(session, sid, "PLATFORM", "illumina")
    _add_attr(session, sid, "platform", "pacbio")    # conflict
    session.commit()

    stats, conflicts = dedupe_attributes(
        session, entity="sample", dry_run=False
    )

    assert stats["merged"] == 1
    assert stats["conflicts"] == 1
    assert stats["tables_processed"] == 1
    assert stats["failed_tables"] == []
    assert len(conflicts) == 1
    assert conflicts[0]["key_lower"] == "platform"
