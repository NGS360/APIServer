"""
Test cases for scripts/grant_role.py

Covers parse_batch and apply_grant. main() is deliberately not exercised: it
opens a connection on core.db.engine, which is built at import time from whatever
.env names, so calling it from the suite would reach a deployed database.
"""
import importlib.util
import pathlib

import pytest
from sqlmodel import Session, select

from api.auth.models import User
from api.project.models import Project
from api.rbac.models import ProjectMember, UserRole
from api.rbac.seed import sync_rbac_catalog


def _load():
    """Import the script by path; scripts/ is not a package."""
    path = pathlib.Path(__file__).parent.parent / "scripts" / "grant_role.py"
    spec = importlib.util.spec_from_file_location("grant_role", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grant_role = _load()


@pytest.fixture
def seeded(session: Session):
    sync_rbac_catalog(session)
    for name in ("alice", "bob"):
        session.add(User(username=name, email=f"{name}@example.com",
                         is_active=True, is_verified=True))
    for pid in ("P-1", "P-2"):
        session.add(Project(project_id=pid, created_by="unknown"))
    session.commit()
    return session


class TestParseBatch:

    def _write(self, tmp_path, text):
        path = tmp_path / "grants.txt"
        path.write_text(text)
        return str(path)

    def test_two_fields_is_a_global_role(self, tmp_path):
        path = self._write(tmp_path, "alice lab_manager\n")
        assert grant_role.parse_batch(path) == [("alice", "lab_manager", None)]

    def test_three_fields_is_a_project_membership(self, tmp_path):
        path = self._write(tmp_path, "alice project_owner P-1\n")
        assert grant_role.parse_batch(path) == [
            ("alice", "project_owner", "P-1")
        ]

    def test_comments_and_blank_lines_are_ignored(self, tmp_path):
        path = self._write(tmp_path, """
            # a comment
            alice lab_manager    # trailing comment

            bob   auditor
        """)
        assert grant_role.parse_batch(path) == [
            ("alice", "lab_manager", None), ("bob", "auditor", None)
        ]

    def test_commas_work_as_separators(self, tmp_path):
        path = self._write(tmp_path, "alice,project_owner,P-1\n")
        assert grant_role.parse_batch(path) == [
            ("alice", "project_owner", "P-1")
        ]

    def test_a_malformed_line_names_the_line_number(self, tmp_path):
        path = self._write(tmp_path, "alice lab_manager\nbob\n")
        with pytest.raises(SystemExit) as exc:
            grant_role.parse_batch(path)
        assert ":2:" in str(exc.value)

    def test_an_empty_file_is_an_error(self, tmp_path):
        """Silently doing nothing would look like success."""
        path = self._write(tmp_path, "# nothing here\n")
        with pytest.raises(SystemExit):
            grant_role.parse_batch(path)

    def test_a_missing_file_errors_cleanly(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            grant_role.parse_batch(str(tmp_path / "nope.txt"))
        assert "cannot read" in str(exc.value)


class TestGlobalGrants:

    def test_grants_a_global_role(self, seeded):
        out = grant_role.apply_grant(seeded, "alice", "lab_manager", None)
        assert "granted lab_manager" in out
        assert len(seeded.exec(select(UserRole)).all()) == 1

    def test_is_idempotent(self, seeded):
        grant_role.apply_grant(seeded, "alice", "lab_manager", None)
        out = grant_role.apply_grant(seeded, "alice", "lab_manager", None)
        assert "already held" in out
        assert len(seeded.exec(select(UserRole)).all()) == 1

    def test_rejects_a_project_role_without_a_project(self, seeded):
        """Granting project_owner globally would apply it to every project, which
        is never what naming no project means."""
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "alice", "project_owner", None)
        assert "pass --project" in str(exc.value)

    def test_unknown_user(self, seeded):
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "nobody", "lab_manager", None)
        assert "No user named nobody" in str(exc.value)

    def test_unknown_role(self, seeded):
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "alice", "nosuchrole", None)
        assert "No role named nosuchrole" in str(exc.value)


class TestProjectGrants:

    def test_adds_a_member(self, seeded):
        out = grant_role.apply_grant(seeded, "alice", "project_contributor", "P-1")
        assert "added to P-1" in out
        assert len(seeded.exec(select(ProjectMember)).all()) == 1

    def test_changing_the_role_of_an_existing_member(self, seeded):
        grant_role.apply_grant(seeded, "alice", "project_viewer", "P-1")
        out = grant_role.apply_grant(seeded, "alice", "project_contributor", "P-1")
        assert "already a member" in out
        assert len(seeded.exec(select(ProjectMember)).all()) == 1

    def test_rejects_a_global_role_with_a_project(self, seeded):
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "alice", "lab_manager", "P-1")
        assert "drop --project" in str(exc.value)

    def test_unknown_project(self, seeded):
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "alice", "project_owner", "P-NOPE")
        assert "no project with id" in str(exc.value)

    def test_the_last_owner_guard_still_applies(self, seeded):
        """
        The script routes through api/rbac/services.py, so the guard that stops a
        project being left ownerless is the same one the admin API enforces --
        not a second implementation that could disagree with it.
        """
        grant_role.apply_grant(seeded, "alice", "project_owner", "P-1")
        with pytest.raises(SystemExit) as exc:
            grant_role.apply_grant(seeded, "alice", "project_viewer", "P-1")
        assert "last owner" in str(exc.value)
