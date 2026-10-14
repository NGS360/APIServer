"""
Closure and permission behaviour for the read routes closed in Phase 1d.

`tests/test_route_coverage.py` proves a guard is *attached* to these routes. It
says nothing about what a caller actually receives, and the two are not the same
claim: a guard citing a permission no role holds is attached and also a permanent
403. So the response codes are asserted here, from all three sides -- anonymous,
authenticated-without-the-permission, and authenticated-with-it.

These three closed together because Airflow finished adopting its API key, which
took the last anonymous caller off them. `GET /files/download` and
`GET /projects/search` were candidates in the same pass and stayed open: each
still had a live anonymous python-requests caller. There is no test for those
here, deliberately -- they are listed in AWAITING_AUTHENTICATION, and the
coverage guard is what holds that line.

A refusal is a 403. There is no enforcement mode any more, so what these
assert is what production does.
"""
import pytest
from fastapi.testclient import TestClient

from api.rbac.permissions import Permission

# (path, the permission its guard requires)
CLOSED_READS = [
    ("/api/v1/projects", Permission.PROJECT_READ),
    ("/api/v1/projects/attributes", Permission.PROJECT_READ),
    ("/api/v1/samples/search", Permission.SAMPLE_READ),
]

IDS = [path for path, _ in CLOSED_READS]


@pytest.mark.parametrize("path,permission", CLOSED_READS, ids=IDS)
def test_anonymous_is_refused(
    unauthenticated_client: TestClient, path: str, permission: Permission
):
    """
    The closure itself, and the reason it had to wait for the consumers.

    401 rather than 403: the guard depends on get_current_active_user, so
    authentication resolves first and an anonymous caller never reaches a
    permission check. No authorization setting could have softened this, which is
    why these needed every caller authenticated first rather than a guard.
    """
    response = unauthenticated_client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path,permission", CLOSED_READS, ids=IDS)
def test_authenticated_without_the_permission_is_refused(
    restricted_client: TestClient, path: str, permission: Permission
):
    """A caller holding no roles gets 403 -- proof the guard is load-bearing."""
    response = restricted_client.get(path)
    assert response.status_code == 403
    assert str(permission) in response.json()["detail"]


@pytest.mark.parametrize("path,permission", CLOSED_READS, ids=IDS)
def test_the_permission_alone_is_enough(
    client_with_permissions, path: str, permission: Permission
):
    """
    The other direction, and the one that matters operationally.

    Every real caller on these routes holds the permission through `member` or
    `auditor`, so granting exactly it must be sufficient. If a route ever needs a
    second permission, this fails here rather than as a production 403.
    """
    api = client_with_permissions([permission])
    response = api.get(path)
    assert response.status_code == 200


def test_member_can_still_read_all_three():
    """
    `member` is granted to every user by the bootstrap backfill, and it holds
    global project:read and sample:read specifically to preserve the pre-RBAC
    "any authenticated user can read anything" behaviour until Phase 6 filters
    rows. If a closure ever required more than `member`, every ordinary user
    loses these reads at enforce.
    """
    from api.rbac.roles import ROLE_DEFINITIONS

    member = {str(p) for p in ROLE_DEFINITIONS["member"].permissions}
    required = {str(p) for _, p in CLOSED_READS}
    assert required <= member, f"member is missing {sorted(required - member)}"
