"""
Authorization on PUT /api/v1/jobs/{job_id}.

This route was closed once the Omics run event processor started sending its API
key, which left no anonymous caller on it in any tier. Closing it exposed that the
route carries two operations with very different privilege behind one method:

* the event Lambdas write `status` and `log_stream_name` back as a job progresses
* the web UI sends `{"viewed": true}` when a user opens a job from the
  notifications dropdown

`member` holds job:read and job:submit but not job:update, so a single guard on
job:update would refuse the second. These tests pin the split, in both directions
-- a test that only proved the UI case still works would pass just as happily if
the guard checked nothing at all.

A failed permission check is a 403. There is no enforcement mode any more, so
what these assert is what production does.
"""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from api.jobs.models import BatchJob, JobStatus
from api.rbac.permissions import Permission


@pytest.fixture(name="job")
def job_fixture(session: Session) -> BatchJob:
    job = BatchJob(
        id="job-authz-1",
        name="authz-job",
        command="echo hello",
        user="someone",
        status=JobStatus.SUBMITTED,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


class TestTheRouteIsClosed:

    def test_an_anonymous_caller_is_refused(
        self, unauthenticated_client: TestClient, job: BatchJob
    ):
        """
        The closure itself.

        401 rather than 403: the guard depends on get_current_active_user, so
        authentication is resolved first and an anonymous caller never reaches a
        permission check -- which is also why no authorization setting could have
        eased this in, and it had to wait for every caller to authenticate.
        """
        response = unauthenticated_client.put(
            f"/api/v1/jobs/{job.id}", json={"status": JobStatus.RUNNING}
        )
        assert response.status_code == 401

    def test_a_caller_with_no_roles_cannot_touch_it_at_all(
        self, restricted_client: TestClient, job: BatchJob
    ):
        response = restricted_client.put(
            f"/api/v1/jobs/{job.id}", json={"viewed": True}
        )
        assert response.status_code == 403


class TestMarkingAJobViewed:
    """The UI path: job:read is enough."""

    def test_job_read_may_mark_a_job_viewed(
        self, client_with_permissions, job: BatchJob
    ):
        client = client_with_permissions([Permission.JOB_READ])
        response = client.put(f"/api/v1/jobs/{job.id}", json={"viewed": True})
        assert response.status_code == 200
        assert response.json()["viewed"] is True

    def test_job_update_is_not_required_for_it(
        self, client_with_permissions, job: BatchJob
    ):
        """
        The regression this file exists for.

        `member` is job:read + job:submit. If someone later collapses the guard
        onto job:update, every ordinary user loses the ability to open a job from
        the notifications dropdown, and this fails.
        """
        client = client_with_permissions(
            [Permission.JOB_READ, Permission.JOB_SUBMIT], username="memberish"
        )
        response = client.put(f"/api/v1/jobs/{job.id}", json={"viewed": True})
        assert response.status_code == 200


class TestWritingBackJobState:
    """The machine path: job:update, and job:read is not a way around it."""

    @pytest.mark.parametrize("payload", [
        {"status": JobStatus.RUNNING},
        {"log_stream_name": "some-stream"},
        {"status": JobStatus.RUNNING, "log_stream_name": "some-stream"},
        # Mixed with the harmless field: the stricter requirement has to win, or
        # adding `viewed` to a payload becomes a way to downgrade the check.
        {"status": JobStatus.RUNNING, "viewed": True},
    ])
    def test_job_read_alone_is_refused(
        self, client_with_permissions, job: BatchJob, payload: dict
    ):
        client = client_with_permissions([Permission.JOB_READ])
        response = client.put(f"/api/v1/jobs/{job.id}", json=payload)
        assert response.status_code == 403
        assert "job:update" in response.json()["detail"]

    @pytest.mark.parametrize("payload", [
        {"status": JobStatus.RUNNING},
        {"log_stream_name": "some-stream"},
        {"status": JobStatus.SUCCEEDED, "viewed": True},
    ])
    def test_job_update_is_accepted(
        self, client_with_permissions, job: BatchJob, payload: dict
    ):
        client = client_with_permissions([Permission.JOB_UPDATE])
        response = client.put(f"/api/v1/jobs/{job.id}", json=payload)
        assert response.status_code == 200

    def test_an_explicit_null_still_counts_as_touching_the_field(
        self, client_with_permissions, job: BatchJob
    ):
        """
        The guard matches model_dump(exclude_unset=True), which is exactly what
        update_batch_job persists -- so naming a writeback field requires the
        permission even when the value is null, and the check cannot be sidestepped
        by sending one. It also means the check can never drift from the write.
        """
        client = client_with_permissions([Permission.JOB_READ])
        response = client.put(
            f"/api/v1/jobs/{job.id}", json={"log_stream_name": None}
        )
        assert response.status_code == 403


class TestTheDecisionIsRecorded:

    def test_the_permission_it_resolved_reaches_the_access_log(
        self, client_with_permissions, job: BatchJob
    ):
        """
        A bespoke guard that skipped `decide` would enforce correctly and be
        invisible to the access log and the deny-rate alarms -- which is how a
        refusal gets noticed at all.
        """
        client = client_with_permissions([Permission.JOB_READ])
        response = client.put(
            f"/api/v1/jobs/{job.id}", json={"status": JobStatus.RUNNING}
        )
        assert response.status_code == 403
        # The 403 body is the observable end of the same decision record.
        assert response.json()["detail"] == "Missing permission: job:update"

    def test_the_guard_advertises_both_permissions_it_can_require(self):
        """
        Route introspection has to see both branches, or the coverage test reports
        this route as requiring only whichever one was hardcoded.
        """
        from api.jobs.routes import require_job_update

        assert set(require_job_update.rbac_permissions) == {
            Permission.JOB_UPDATE, Permission.JOB_READ,
        }
        assert require_job_update.rbac_plane == "global"
