"""
Test cases for the user administration surface: the roster, one user's
effective access, and the status flags.

The lockout guards get the most attention here. is_active and is_verified are
both required to authenticate, so clearing either is a lockout, and two of those
lockouts cannot be undone through the API afterwards -- the last usable
superuser and the last non-superuser role manager.
"""
import pytest
from sqlmodel import Session

from api.auth.models import User
from api.rbac import services as rbac_services
from api.rbac.models import ProjectMember, Role, UserRole
from api.rbac.seed import sync_rbac_catalog


@pytest.fixture
def seeded(session: Session):
    sync_rbac_catalog(session)
    return session


def _user(
    session: Session, username: str, *, superuser: bool = False,
    active: bool = True, verified: bool = True, full_name: str | None = None,
) -> User:
    user = User(username=username, email=f"{username}@example.com",
                full_name=full_name, is_active=active, is_verified=verified,
                is_superuser=superuser)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def _grant(session: Session, user: User, role_name: str) -> Role:
    role = rbac_services.get_role_or_404(session, role_name)
    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.commit()
    return role


class TestUserRoster:

    def test_lists_every_local_account(self, superuser_client, seeded):
        _user(seeded, "alice")
        _user(seeded, "bob")
        r = superuser_client.get("/api/v1/rbac/users")
        assert r.status_code == 200
        usernames = [u["username"] for u in r.json()["data"]]
        assert usernames == ["admin", "alice", "bob"]

    def test_includes_deactivated_accounts(self, superuser_client, seeded):
        """
        The difference from GET /users/search that matters. That endpoint backs
        the user picker and filters to is_active, which makes it useless for the
        administrator whose whole reason for opening the page is the account
        somebody deactivated.
        """
        _user(seeded, "departed", active=False)
        usernames = [
            u["username"]
            for u in superuser_client.get("/api/v1/rbac/users").json()["data"]
        ]
        assert "departed" in usernames

    def test_carries_the_status_flags_and_global_roles(
        self, superuser_client, seeded
    ):
        alice = _user(seeded, "alice", verified=False)
        _grant(seeded, alice, "lab_manager")
        _grant(seeded, alice, "auditor")

        row = next(
            u for u in superuser_client.get("/api/v1/rbac/users").json()["data"]
            if u["username"] == "alice"
        )
        assert row["is_active"] is True
        assert row["is_verified"] is False
        assert row["is_superuser"] is False
        assert row["global_roles"] == ["auditor", "lab_manager"]

    def test_filters_on_username_email_or_full_name(
        self, superuser_client, seeded
    ):
        _user(seeded, "alice", full_name="Alice Zhang")
        _user(seeded, "bob", full_name="Bob Jones")

        by_name = superuser_client.get("/api/v1/rbac/users?q=zhang").json()
        assert [u["username"] for u in by_name["data"]] == ["alice"]

        by_email = superuser_client.get("/api/v1/rbac/users?q=bob@").json()
        assert [u["username"] for u in by_email["data"]] == ["bob"]

    def test_filters_on_role(self, superuser_client, seeded):
        alice = _user(seeded, "alice")
        _user(seeded, "bob")
        _grant(seeded, alice, "auditor")

        r = superuser_client.get("/api/v1/rbac/users?role=auditor")
        assert [u["username"] for u in r.json()["data"]] == ["alice"]

    def test_an_unknown_role_filter_is_404(self, superuser_client, seeded):
        """
        Rather than an empty page, which would read as "nobody holds this" and
        hide the typo.
        """
        r = superuser_client.get("/api/v1/rbac/users?role=ghost")
        assert r.status_code == 404
        assert "ghost" in r.json()["detail"]

    def test_filters_on_status(self, superuser_client, seeded):
        _user(seeded, "alice")
        _user(seeded, "departed", active=False)

        active = superuser_client.get("/api/v1/rbac/users?is_active=true").json()
        assert "departed" not in [u["username"] for u in active["data"]]

        inactive = superuser_client.get(
            "/api/v1/rbac/users?is_active=false"
        ).json()
        assert [u["username"] for u in inactive["data"]] == ["departed"]

    def test_paginates(self, superuser_client, seeded):
        for name in ("alice", "bob", "carol"):
            _user(seeded, name)

        first = superuser_client.get("/api/v1/rbac/users?skip=0&limit=2").json()
        assert first["total_items"] == 4  # the three above, plus admin
        assert [u["username"] for u in first["data"]] == ["admin", "alice"]
        assert first["has_next"] is True
        assert first["has_prev"] is False

        second = superuser_client.get("/api/v1/rbac/users?skip=2&limit=2").json()
        assert [u["username"] for u in second["data"]] == ["bob", "carol"]
        assert second["has_next"] is False
        assert second["has_prev"] is True

    def test_sorts(self, superuser_client, seeded):
        _user(seeded, "alice")
        r = superuser_client.get(
            "/api/v1/rbac/users?sort_by=username&sort_order=desc"
        )
        assert [u["username"] for u in r.json()["data"]] == ["alice", "admin"]

    def test_rejects_an_unknown_sort_field(self, superuser_client, seeded):
        """A sort field is a whitelist, not an attribute lookup."""
        r = superuser_client.get("/api/v1/rbac/users?sort_by=hashed_password")
        assert r.status_code == 422

    def test_requires_superuser(self, client, seeded):
        assert client.get("/api/v1/rbac/users").status_code == 403


class TestUserAccess:

    def test_reports_both_grant_planes(
        self, superuser_client, seeded, test_project
    ):
        alice = _user(seeded, "alice")
        _grant(seeded, alice, "lab_manager")
        owner = rbac_services.get_role_or_404(seeded, "project_owner")
        seeded.add(ProjectMember(project_id=test_project.id, user_id=alice.id,
                                 role_id=owner.id))
        seeded.commit()

        body = superuser_client.get("/api/v1/rbac/users/alice/access").json()
        assert body["global_roles"] == ["lab_manager"]
        assert "run:demux" in body["global_permissions"]
        assert body["project_memberships"] == [{
            "project_id": test_project.project_id,
            "project_name": test_project.name,
            "role": "project_owner",
            "granted_at": body["project_memberships"][0]["granted_at"],
            "source": "manual",
        }]

    def test_a_user_with_nothing_reports_empty_rather_than_erroring(
        self, superuser_client, seeded
    ):
        _user(seeded, "newcomer")
        body = superuser_client.get(
            "/api/v1/rbac/users/newcomer/access"
        ).json()
        assert body["global_roles"] == []
        assert body["global_permissions"] == []
        assert body["project_memberships"] == []

    def test_a_superuser_reports_the_whole_catalog(
        self, superuser_client, seeded
    ):
        """
        Which is what the flag means. An empty list would read as "no access"
        for the one account that has all of it.
        """
        from api.rbac.permissions import ALL_PERMISSIONS

        body = superuser_client.get("/api/v1/rbac/users/admin/access").json()
        assert body["is_superuser"] is True
        assert len(body["global_permissions"]) == len(ALL_PERMISSIONS)

    def test_unknown_user_is_404(self, superuser_client, seeded):
        assert superuser_client.get(
            "/api/v1/rbac/users/ghost/access"
        ).status_code == 404

    def test_requires_superuser(self, client, seeded):
        assert client.get(
            "/api/v1/rbac/users/testuser/access"
        ).status_code == 403


class TestUserFlags:

    def test_verifies_an_account(self, superuser_client, seeded):
        _user(seeded, "alice", verified=False)
        r = superuser_client.patch("/api/v1/users/alice",
                                   json={"is_verified": True})
        assert r.status_code == 200
        assert r.json()["is_verified"] is True

    def test_leaves_omitted_fields_alone(self, superuser_client, seeded):
        """
        Omission means "do not touch". A client that only wants to verify an
        account must not be able to clear the other two by sending a partially
        populated object.
        """
        _user(seeded, "alice", verified=False)
        body = superuser_client.patch("/api/v1/users/alice",
                                      json={"is_verified": True}).json()
        assert body["is_active"] is True
        assert body["is_superuser"] is False

    def test_deactivates_an_account(self, superuser_client, seeded):
        _user(seeded, "departing")
        r = superuser_client.patch("/api/v1/users/departing",
                                   json={"is_active": False})
        assert r.status_code == 200
        assert r.json()["is_active"] is False

    def test_reports_the_users_global_roles_back(self, superuser_client, seeded):
        alice = _user(seeded, "alice")
        _grant(seeded, alice, "auditor")
        body = superuser_client.patch("/api/v1/users/alice",
                                      json={"is_verified": True}).json()
        assert body["global_roles"] == ["auditor"]

    def test_promotes_and_demotes_a_superuser(self, superuser_client, seeded):
        _user(seeded, "alice")
        assert superuser_client.patch(
            "/api/v1/users/alice", json={"is_superuser": True}
        ).json()["is_superuser"] is True
        # admin is still a usable superuser, so this one may be demoted.
        assert superuser_client.patch(
            "/api/v1/users/alice", json={"is_superuser": False}
        ).json()["is_superuser"] is False

    def test_refuses_to_lock_out_the_caller(self, superuser_client, seeded):
        for field in ("is_active", "is_verified"):
            r = superuser_client.patch("/api/v1/users/admin", json={field: False})
            assert r.status_code == 409, field
            assert "lock you out" in r.json()["detail"]

    def test_refuses_to_remove_the_callers_own_superuser(
        self, superuser_client, seeded
    ):
        r = superuser_client.patch("/api/v1/users/admin",
                                   json={"is_superuser": False})
        assert r.status_code == 409
        assert "your own superuser" in r.json()["detail"]

    def test_refuses_to_lock_out_the_last_usable_superuser(self, seeded):
        """
        Reachable only from a caller who is not themselves a superuser: any
        superuser calling this is, by definition, another usable one. So the
        case the guard exists for is a user:manage holder deactivating the last
        superuser account -- and the flags route is exactly the way to do it,
        since deactivation needs no superuser of its own.
        """
        actor = _user(seeded, "role_admin")
        _grant(seeded, actor, "admin")  # carries user:manage, not the flag
        target = _user(seeded, "root", superuser=True)

        with pytest.raises(Exception) as exc:
            rbac_services.update_user_flags(
                seeded, target, acting_user=actor, is_active=False
            )
        assert exc.value.status_code == 409
        assert "only superuser" in exc.value.detail

    def test_counts_only_superusers_who_could_sign_in(self, seeded):
        """
        A superuser row that cannot authenticate is not a way back in, so it
        must not satisfy the guard: get_current_active_user requires both flags.
        """
        actor = _user(seeded, "role_admin")
        _grant(seeded, actor, "admin")
        _user(seeded, "shelved", superuser=True, active=False)
        _user(seeded, "unverified_su", superuser=True, verified=False)
        target = _user(seeded, "root", superuser=True)

        with pytest.raises(Exception) as exc:
            rbac_services.update_user_flags(
                seeded, target, acting_user=actor, is_active=False
            )
        assert exc.value.status_code == 409

    def test_allows_the_lockout_when_another_usable_superuser_remains(
        self, seeded
    ):
        actor = _user(seeded, "role_admin")
        _grant(seeded, actor, "admin")
        spare = _user(seeded, "spare_root", superuser=True)
        target = _user(seeded, "root", superuser=True)

        updated = rbac_services.update_user_flags(
            seeded, target, acting_user=actor, is_active=False
        )
        assert updated.is_active is False
        assert spare.is_superuser is True

    def test_refuses_to_lock_out_the_last_role_manager(
        self, superuser_client, seeded
    ):
        """
        Deactivation revokes everything the account holds, so it has to answer
        to the same rule as revoking role:manage directly -- otherwise the guard
        on DELETE /rbac/users/{u}/roles/{r} is trivially sidestepped.
        """
        alice = _user(seeded, "alice")
        _grant(seeded, alice, "admin")  # the admin role carries role:manage

        r = superuser_client.patch("/api/v1/users/alice",
                                   json={"is_active": False})
        assert r.status_code == 409
        assert "role:manage" in r.json()["detail"]

    def test_allows_the_lockout_once_another_role_manager_exists(
        self, superuser_client, seeded
    ):
        alice = _user(seeded, "alice")
        bob = _user(seeded, "bob")
        _grant(seeded, alice, "admin")
        _grant(seeded, bob, "admin")

        assert superuser_client.patch(
            "/api/v1/users/alice", json={"is_active": False}
        ).status_code == 200

    def test_unknown_user_is_404(self, superuser_client, seeded):
        assert superuser_client.patch(
            "/api/v1/users/ghost", json={"is_active": False}
        ).status_code == 404

    def test_requires_superuser(self, client, seeded):
        assert client.patch(
            "/api/v1/users/testuser", json={"is_verified": True}
        ).status_code == 403


class TestSuperuserFlagNeedsMoreThanUserManage:
    """
    docs/RBAC.md: setting is_superuser takes user:manage AND superuser, never
    user:manage alone. The route's CurrentSuperuser dependency makes that true
    today; the check is enforced in the service so it stays true if the route
    ever moves onto the permission by itself.
    """

    def test_a_non_superuser_holder_cannot_set_the_flag(self, seeded):
        actor = _user(seeded, "role_admin")
        _grant(seeded, actor, "admin")
        target = _user(seeded, "alice")

        with pytest.raises(Exception) as exc:
            rbac_services.update_user_flags(
                seeded, target, acting_user=actor, is_superuser=True
            )
        assert exc.value.status_code == 403
        assert "superuser" in exc.value.detail

    def test_the_same_holder_may_still_verify_an_account(self, seeded):
        actor = _user(seeded, "role_admin")
        _grant(seeded, actor, "admin")
        target = _user(seeded, "alice", verified=False)

        updated = rbac_services.update_user_flags(
            seeded, target, acting_user=actor, is_verified=True
        )
        assert updated.is_verified is True
