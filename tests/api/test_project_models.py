"""
Unit tests for Project API models.
"""

from datetime import datetime

import pytest

from api.project.models import ProjectPublic


def _make_project(**overrides):
    """Build a ProjectPublic with sensible defaults, overriding as needed."""
    data = dict(
        project_id="P-20260101-0001",
        name="Test Project",
        created_by="testuser",
        created_at="2026-01-01 00:00:00",
        last_modified="2026-01-01 00:00:00",
        data_folder_uri=None,
        results_folder_uri=None,
        attributes=None,
    )
    data.update(overrides)
    return ProjectPublic(**data)


def test_valid_datetime_strings_are_parsed():
    """Valid date strings are parsed into datetime instances."""
    project = _make_project(
        created_at="2026-01-01 12:30:00",
        last_modified="2026-06-15 08:00:00",
    )
    assert project.created_at == datetime(2026, 1, 1, 12, 30, 0)
    assert project.last_modified == datetime(2026, 6, 15, 8, 0, 0)


@pytest.mark.parametrize(
    "bad_value",
    [
        "1000-00-01 00:00:00",  # month 0 (the reported production value)
        "0000-00-00 00:00:00",  # classic MySQL zero date
        "2026-13-01 00:00:00",  # month out of range
        "not-a-date",           # entirely unparseable
    ],
)
def test_invalid_datetime_strings_become_none(bad_value):
    """Unparseable/zero dates are coerced to None instead of raising."""
    project = _make_project(created_at=bad_value, last_modified=bad_value)
    assert project.created_at is None
    assert project.last_modified is None


def test_none_datetime_is_allowed():
    """Explicit None passes through unchanged."""
    project = _make_project(created_at=None, last_modified=None)
    assert project.created_at is None
    assert project.last_modified is None


def test_actual_datetime_objects_pass_through():
    """A real datetime object is accepted as-is."""
    now = datetime(2026, 7, 1, 11, 27, 33)
    project = _make_project(created_at=now, last_modified=now)
    assert project.created_at == now
    assert project.last_modified == now
