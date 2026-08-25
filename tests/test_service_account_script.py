"""
Tests for scripts/create_service_account.py --revoke-key and the tier confirmation.

The revoke path is the one that takes access away, and the one where a mistake is
silent: a mistyped --except-key would revoke the very key it names, and a key
missed by find_active_keys goes on authenticating after a run that reported
success. Both are covered here.

confirm_target is the guard in front of both paths -- it is what stands between
"mint a key" and "mint a key in the wrong tier" -- so its refusals matter as much
as its acceptance, and are covered too.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from api.auth.models import APIKey, APIKeyCreate, User
from api.auth.services import create_user_api_key
from scripts import create_service_account as script


@pytest.fixture(name="svc")
def svc_fixture(session):
    """A service account shaped the way the script creates them."""
    user = User(
        username="svc-test",
        email="svc-test@ngs360.invalid",
        full_name="Service account: svc-test",
        hashed_password=None,
        is_active=True,
        is_verified=True,
    )
    session.add(user)
    session.commit()
    return user


def mint(session, user, name="key"):
    """Mint a key the same way the script does. Returns (row, raw_key)."""
    return create_user_api_key(session, user, APIKeyCreate(name=name))


def active_prefixes(session, user):
    return {
        k.key_prefix
        for k in session.exec(
            select(APIKey).where(
                APIKey.user_id == user.id, APIKey.is_active.is_(True)
            )
        ).all()
    }


def test_revokes_every_active_key(session, svc):
    old, _ = mint(session, svc, "old")
    new, _ = mint(session, svc, "new")

    assert script.run_revoke(session, "svc-test", [], dry_run=False) == 0

    assert active_prefixes(session, svc) == set()
    for key in (old, new):
        session.refresh(key)
        assert key.is_active is False
        assert key.revoked_at is not None


def test_revoked_key_no_longer_authenticates(session, svc):
    """The point of the flag: the old token stops working, the spared one does not."""
    from fastapi import HTTPException

    from api.auth.deps import authenticate_api_key

    _, old_raw = mint(session, svc, "old")
    _, new_raw = mint(session, svc, "new")

    script.run_revoke(session, "svc-test", [new_raw], dry_run=False)

    with pytest.raises(HTTPException) as excinfo:
        authenticate_api_key(session, old_raw)
    assert excinfo.value.status_code == 401

    assert authenticate_api_key(session, new_raw).username == "svc-test"


def test_revoke_is_soft_so_the_row_survives(session, svc):
    key, _ = mint(session, svc, "old")
    key_id = key.id

    script.run_revoke(session, "svc-test", [], dry_run=False)

    # Still there to be audited -- name, prefix and last_used_at intact.
    row = session.exec(select(APIKey).where(APIKey.id == key_id)).first()
    assert row is not None
    assert row.name == "old"


def test_except_key_spares_the_key_you_just_deployed(session, svc):
    old, _ = mint(session, svc, "old")
    new, new_raw = mint(session, svc, "new")

    script.run_revoke(session, "svc-test", [new_raw], dry_run=False)

    session.refresh(old)
    session.refresh(new)
    assert old.is_active is False
    assert new.is_active is True
    assert new.revoked_at is None


@pytest.mark.parametrize("form", ["id", "prefix", "raw"])
def test_except_key_accepts_id_prefix_or_raw_key(session, svc, form):
    old, _ = mint(session, svc, "old")
    new, new_raw = mint(session, svc, "new")

    token = {"id": str(new.id), "prefix": new.key_prefix, "raw": new_raw}[form]
    script.run_revoke(session, "svc-test", [token], dry_run=False)

    session.refresh(old)
    session.refresh(new)
    assert new.is_active is True, f"--except-key by {form} did not spare the key"
    assert old.is_active is False


def test_unknown_except_key_aborts_before_revoking_anything(session, svc):
    old, _ = mint(session, svc, "old")
    new, _ = mint(session, svc, "new")

    # A typo in the prefix of the key being kept must not fall through to
    # "revoke everything, including that one".
    with pytest.raises(SystemExit) as excinfo:
        script.run_revoke(session, "svc-test", ["ngs360_typo0"], dry_run=False)
    assert "matches no active key" in str(excinfo.value)

    assert active_prefixes(session, svc) == {old.key_prefix, new.key_prefix}


def test_excepting_every_key_revokes_nothing(session, svc):
    only, raw = mint(session, svc, "only")

    assert script.run_revoke(session, "svc-test", [raw], dry_run=False) == 0

    session.refresh(only)
    assert only.is_active is True


def test_dry_run_writes_nothing(session, svc):
    key, _ = mint(session, svc, "old")

    assert script.run_revoke(session, "svc-test", [], dry_run=True) == 0

    session.refresh(key)
    assert key.is_active is True
    assert key.revoked_at is None


def test_dry_run_still_validates_except_key(session, svc):
    mint(session, svc, "old")

    with pytest.raises(SystemExit):
        script.run_revoke(session, "svc-test", ["nope"], dry_run=True)


def test_already_revoked_keys_are_left_alone(session, svc):
    done, _ = mint(session, svc, "already revoked")
    revoked_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    done.is_active = False
    done.revoked_at = revoked_at
    session.add(done)
    session.commit()

    script.run_revoke(session, "svc-test", [], dry_run=False)

    session.refresh(done)
    # revoked_at is not overwritten, so the audit trail keeps the first date.
    assert script.ensure_timezone_aware(done.revoked_at) == revoked_at


def test_account_with_no_keys_is_not_an_error(session, svc):
    assert script.run_revoke(session, "svc-test", [], dry_run=False) == 0


def test_unknown_username_aborts(session, svc):
    with pytest.raises(SystemExit) as excinfo:
        script.run_revoke(session, "svc-nonexistent", [], dry_run=False)
    assert "no user" in str(excinfo.value)


def test_keys_of_other_accounts_are_untouched(session, svc):
    other = User(username="svc-other", email="svc-other@ngs360.invalid",
                 is_active=True, is_verified=True)
    session.add(other)
    session.commit()
    theirs, _ = mint(session, other, "theirs")
    mint(session, svc, "ours")

    script.run_revoke(session, "svc-test", [], dry_run=False)

    session.refresh(theirs)
    assert theirs.is_active is True


def test_recently_used_survives_naive_timestamps(session, svc):
    """MySQL hands back naive datetimes; comparing them to an aware now() raises."""
    key, _ = mint(session, svc, "in use")
    key.last_used_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(key)
    session.commit()

    assert script.recently_used([key]) == [key]


def test_recently_used_ignores_old_and_unused_keys(session, svc):
    stale, _ = mint(session, svc, "stale")
    stale.last_used_at = datetime.now(timezone.utc) - timedelta(days=30)
    never, _ = mint(session, svc, "never used")
    session.add(stale)
    session.commit()

    assert script.recently_used([stale, never]) == []


class FakeSettings:
    """confirm_target reads nothing but the tier off settings."""

    def __init__(self, environment="prod"):
        self.ENVIRONMENT = environment


@pytest.fixture(name="tty")
def tty_fixture(monkeypatch):
    """Make the script believe it is attached to a terminal."""
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: True, raising=False)


def answer(monkeypatch, value):
    """Answer the confirmation prompt with `value`, or raise it if it is an exception."""
    def fake_input(_prompt=""):
        if isinstance(value, type) and issubclass(value, BaseException):
            raise value
        return value
    monkeypatch.setattr("builtins.input", fake_input)


def test_confirm_accepts_the_tier_name(monkeypatch, tty):
    answer(monkeypatch, "prod")
    script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=False)


@pytest.mark.parametrize("typed", [" prod ", "PROD", "Prod\n"])
def test_confirm_ignores_case_and_surrounding_space(monkeypatch, tty, typed):
    # The operator is copying a word off the screen, not entering a password.
    answer(monkeypatch, typed)
    script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=False)


@pytest.mark.parametrize("typed", ["dev", "", "y", "yes"])
def test_confirm_rejects_anything_else(monkeypatch, tty, typed):
    # Notably "y"/"yes": the prompt is deliberately not a y/N, and reflexively
    # answering it as one must not get through.
    answer(monkeypatch, typed)
    with pytest.raises(SystemExit) as excinfo:
        script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=False)
    assert "nothing written" in str(excinfo.value)


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_confirm_treats_interruption_as_refusal(monkeypatch, tty, interruption):
    answer(monkeypatch, interruption)
    with pytest.raises(SystemExit) as excinfo:
        script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=False)
    assert "aborted, nothing written" in str(excinfo.value)


def test_confirm_aborts_when_there_is_no_terminal_to_ask(monkeypatch):
    # Rather than blocking forever on a read that will never be answered, or
    # -- worse -- proceeding unconfirmed under cron or a pipe.
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(SystemExit) as excinfo:
        script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=False)
    assert "stdin is not a terminal" in str(excinfo.value)


def test_yes_skips_the_prompt_entirely(monkeypatch):
    monkeypatch.setattr(script.sys.stdin, "isatty", lambda: False, raising=False)
    answer(monkeypatch, AssertionError)  # asking at all is the failure
    script.confirm_target(FakeSettings("prod"), "mint a key", assume_yes=True)
