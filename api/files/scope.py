"""
Resolve an S3 URI to the projects whose membership governs it.

`GET /files/download-url` takes an arbitrary URI, so until now it could only be
guarded globally: nothing mapped a URI back to a project, which meant every
authenticated caller could download any file in the product. Files *are*
associated, though — `fileproject`, `filesample` and `filesequencingrun` all exist
— so the mapping is available, and this module is it.

Two resolution strategies, and the order between them is the policy:

**Direct, and preferred.** A file associated with a project (`fileproject`) or with
a sample (`filesample`, and a sample belongs to exactly one project) resolves to
those projects and no others. Strict: known project, no widening.

**Through the run, only as a fallback.** A file with no project or sample
association but attached to a sequencing run resolves to *every* project that run
touches, reached via its samples. Permissive by decision: a flowcell is a shared
artifact — demux statistics and samplesheets belong to the run rather than to one
project — and requiring a separate grant for routine lab work would generate a
request per person per flowcell.

The order matters and is the whole distinction. A file that is both in a project
and on a run resolves *strictly*, through its project. Widening it through the run
would quietly turn the strict case into the permissive one, which is the mistake
this ordering exists to prevent.

**Path inference, as a last resort.** A URI with no association at all, but which
sits under a project id inside the configured data or results bucket, is treated
as belonging to that project. This was added deliberately after production
measurement: 63 of 75 unresolvable download attempts were pipeline *output* --
zUMIs count matrices, multiqc reports, WES variant calls -- written to
`<results-bucket>/<project-id>/...` and never registered as File rows. Those are
the scientific product, they plainly belong to the project whose id is in the
path, and refusing them would refuse the most legitimate traffic on the endpoint.

Two constraints make this safe rather than a hole, and both matter:

* **Only the configured DATA_BUCKET_URI and RESULTS_BUCKET_URI count.** The guard
  decides whether to mint a presigned URL against our own S3 credentials, so
  inferring a project from *any* bucket would let a member of project X reach any
  object whose key happens to contain that project id, anywhere the API's role can
  read. Restricting to the two buckets the platform itself writes keeps the
  inference inside data NGS360 already owns.
* **The project must exist.** A path naming a project that is not in the database
  resolves to nothing; it does not invent a scope.

Inference runs last, after every real association, and is reported as its own
origin so the proportion of access granted by convention rather than by record
stays visible -- and can be watched shrinking as pipelines start registering their
outputs.

A URI that resolves to nothing even then is not downloadable. "This file belongs
to no project" is not evidence of permission.
"""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session, select

from api.files.models import File, FileProject, FileSample, FileSequencingRun
from api.project.models import Project
from api.vendors.models import Vendor
from api.runs.models import SampleSequencingRun, SequencingRun
from api.samples.models import Sample
from api.settings.services import get_setting_value

#: Project ids are generated as P-YYYYMMDD-NNNN by generate_project_id. Anchored to
#: a path segment so a substring inside a filename cannot be mistaken for one.
_PROJECT_ID = re.compile(r"(?:^|/)(P-\d{8}-\d{4})(?:/|$)")

#: The settings naming the buckets the platform writes. Inference is confined to
#: these; see the module docstring for why that is the security boundary.
_OWNED_BUCKET_SETTINGS = ("DATA_BUCKET_URI", "RESULTS_BUCKET_URI")

#: How a URI was resolved. Recorded on the access log so the mix is measurable --
#: in particular "path", which is access granted by naming convention rather than
#: by a registered association and should trend towards zero.
Origin = Literal["project", "sample", "run", "run-folder", "file-store", "path",
                 "vendor-path", "unregistered", "unassociated"]


@dataclass(frozen=True)
class FileScope:
    """The projects governing a URI, and how they were arrived at."""

    project_ids: frozenset[uuid.UUID]
    origin: Origin

    #: Allowed for any authenticated caller, without resolving a project at all.
    #: Set only for run-folder contents -- see `_under_a_run_folder`. Distinct
    #: from `resolved`: there is no project here to carry a restriction, so the
    #: caller is allowed on the strength of where the file sits.
    open_to_authenticated: bool = False

    @property
    def resolved(self) -> bool:
        return bool(self.project_ids)


def _file_ids(session: Session, uri: str) -> list[uuid.UUID]:
    """
    Every File row for this URI.

    `uri` is deliberately not unique — the same path is re-registered on each
    upload to give versioning, with `(uri, created_on)` as the real key. Any
    version's associations are equally good for deciding who may download the
    bytes at that path, so all of them count.
    """
    return list(session.exec(select(File.id).where(File.uri == uri)).all())


def _projects_direct(session: Session, file_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Project associations, plus the project each associated sample belongs to."""
    direct = set(session.exec(
        select(FileProject.project_id).where(FileProject.file_id.in_(file_ids))
    ).all())

    # filesample points at sample.id; a sample carries the project's *string*
    # business key, so this needs the join back to project.id.
    via_sample = session.exec(
        select(Project.id)
        .join(Sample, Sample.project_id == Project.project_id)
        .join(FileSample, FileSample.sample_id == Sample.id)
        .where(FileSample.file_id.in_(file_ids))
    ).all()

    return direct | set(via_sample)


def _projects_via_run(session: Session, file_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """
    Every project the file's sequencing runs touch.

    A run reaches projects only through its samples, which is exactly why a run
    cannot be pinned to one project and why this path is the permissive one.
    """
    run_ids = session.exec(
        select(FileSequencingRun.sequencing_run_id)
        .where(FileSequencingRun.file_id.in_(file_ids))
    ).all()
    if not run_ids:
        return set()

    return set(session.exec(
        select(Project.id)
        .join(Sample, Sample.project_id == Project.project_id)
        .join(SampleSequencingRun, SampleSequencingRun.sample_id == Sample.id)
        .where(SampleSequencingRun.sequencing_run_id.in_(list(run_ids)))
    ).all())


def _normalise(uri: str) -> str:
    """Strip a trailing slash so bucket prefixes compare cleanly."""
    return (uri or "").rstrip("/")


def _storage_root() -> str:
    """
    Where `POST /files/upload` writes, from configuration.

    Read from `get_settings()` and *not* from `get_setting_value`, which is the
    database `setting` table. The two look interchangeable and are not:
    DATA_BUCKET_URI and RESULTS_BUCKET_URI are database settings, while
    STORAGE_ROOT_PATH comes from the STORAGE_URI environment variable and has no
    row at all. Looking it up in the database returns None, which silently made
    the file store unsignable -- and so made every upload a 403.
    """
    from core.config import get_settings

    return _normalise(get_settings().STORAGE_ROOT_PATH)


def _vendor_prefixes(session: Session) -> list[str]:
    """
    The inbound prefixes of registered vendors, from `vendor.bucket`.

    Vendors deliver into `s3://<bucket>/incoming/<project-id>/...`, so these are
    platform-owned drop boxes rather than third-party buckets -- the same class
    of location as the data and results buckets, just named in a table instead
    of a setting.

    **The allowlist is only as trustworthy as who may write that column.** With
    `vendor:create` and `vendor:update` held broadly, any holder could point a
    vendor row at an arbitrary bucket and make it inferable. Those two
    permissions move to `vendor_admin` in step 3 of the role model (NWP-2213);
    until then this inference widens what can be signed to anyone who can edit
    a vendor. Recorded here because the two changes have to land in that order
    to be coherent, and this one is first.
    """
    rows = session.exec(
        select(Vendor.bucket).where(
            Vendor.bucket.is_not(None), Vendor.bucket != ""
        )
    ).all()
    return [_normalise(b) for b in rows if b]


def _project_from_path(session: Session, uri: str) -> set[uuid.UUID]:
    """
    The project whose id appears in this URI, if the URI is in a bucket we own.

    Returns an empty set unless *all* of the following hold: the URI sits under
    DATA_BUCKET_URI or RESULTS_BUCKET_URI, a path segment matches the project-id
    format, and a project with that id exists. Anything less resolves to nothing
    rather than to a guess.
    """
    target = _normalise(uri)

    # Unset settings must not become an empty prefix that matches everything --
    # that would extend inference to every bucket the API can read.
    prefixes = [
        b for b in (_normalise(get_setting_value(session, key))
                    for key in _OWNED_BUCKET_SETTINGS) if b
    ]
    # Vendor inbound prefixes, added 2026-10-08. Measured first: all 89 download
    # requests into vendor buckets over 28 days named a project id that exists,
    # and none lacked one -- so these resolve to a project like any other
    # inferred path, rather than needing a category that is signable without
    # one. That matters because it means a restricted project still restricts
    # its vendor deliveries.
    prefixes += _vendor_prefixes(session)
    # The upload store, so a file written to `<root>/project/<project-id>/...`
    # resolves to that project and inherits its restriction. Uploads against a
    # run, sample or QC record carry no project id and fall through to the
    # file-store location instead.
    root = _storage_root()
    if root:
        prefixes.append(root)
    # Longest match, so a results bucket nested inside a data bucket strips the
    # more specific prefix rather than leaving "results/" in the path.
    matched = max(
        (p for p in prefixes if target.startswith(p + "/")),
        key=len, default=None,
    )
    if matched is None:
        return set()

    match = _PROJECT_ID.search(target[len(matched):])
    if not match:
        return set()

    project_id = session.exec(
        select(Project.id).where(Project.project_id == match.group(1))
    ).first()
    return {project_id} if project_id else set()


def _prefixes(uri: str) -> list[str]:
    """
    A URI and every parent prefix of it, longest first, cut at segment
    boundaries.

    Segment boundaries are the point: generating prefixes rather than comparing
    with `startswith` is what stops `s3://b/illumina/RUN-decoy/x` matching a run
    folder of `s3://b/illumina/RUN`.

    The URI itself is included, which it was not when this was written for
    downloads alone. `GET /files/list` is given a *folder*, and the run page
    browses exactly `run_folder_uri` -- so excluding self would refuse the one
    listing the UI actually performs. For a download the self case is harmless:
    the key names a prefix, and S3 has nothing to return for it.
    """
    parts = _normalise(uri).split("/")
    # parts[:3] is "s3:", "", "<bucket>", so i stops at 4: the shallowest
    # candidate is bucket plus one segment. The bucket root is excluded
    # deliberately -- a run row whose run_folder_uri was somehow just a bucket
    # would otherwise open every object in it.
    return ["/".join(parts[:i]) for i in range(len(parts), 3, -1)]


def _under_a_run_folder(session: Session, uri: str) -> bool:
    """
    Does this URI sit inside a registered sequencing run's folder?

    Run folders are opened to every authenticated caller: a flowcell's contents
    are operational lab data, the run page offers the folder for browsing, and
    the alternative measured out at roughly half of recent runs reaching no
    project at all (3% across all history), so project resolution cannot carry
    this traffic. See docs/RBAC.md, "Run folders are open to authenticated
    callers".

    **This includes raw base calls.** A run folder holds
    `Data/Intensities/BaseCalls/**.cbcl` alongside the QC reports, and cbcl is
    decodable into reads, so this opens instrument-level sequence data to every
    platform user. That was the deliberate choice -- the narrower option was an
    allowlist of report subpaths, which covered all of the observed traffic --
    and it is recorded here because the next person to read this rule should
    know it was a decision rather than an oversight.

    What keeps it bounded is the run having been *registered*: the prefix is
    matched against `sequencingrun.run_folder_uri`, a value the platform wrote
    when it ingested the run. An arbitrary bucket and key does not match, which
    is what stops this becoming the arbitrary-S3-read proxy the unresolved
    branch exists to prevent. No bucket allowlist is needed and none is used --
    the registered folder is a stronger statement than a bucket prefix, and it
    covers ONT and Illumina layouts without either being special-cased.

    One indexed `IN` query over the URI's parent prefixes, which is a handful of
    values even for a deep base-calls path.
    """
    prefixes = _prefixes(uri)
    if not prefixes:
        return False

    # Stored values may or may not carry a trailing slash; normalise both sides.
    candidates = session.exec(
        select(SequencingRun.run_folder_uri)
        .where(SequencingRun.run_folder_uri.in_(prefixes))
        .limit(1)
    ).first()
    if candidates is not None:
        return True

    # Fall back to comparing normalised values when the stored URI has a
    # trailing slash, which the IN above would have missed.
    slashed = [p + "/" for p in prefixes]
    return session.exec(
        select(SequencingRun.run_folder_uri)
        .where(SequencingRun.run_folder_uri.in_(slashed))
        .limit(1)
    ).first() is not None


def _under_the_file_store(session: Session, uri: str) -> bool:
    """
    Is this URI inside the platform's own upload store?

    `POST /files/upload` writes to `STORAGE_ROOT_PATH/<entity-type>/<entity-id>/`
    -- in production a dedicated prefix inside a dedicated bucket, distinct from
    both the data and results buckets. Everything there was put there by this
    application, which makes it as platform-owned as a run folder.

    It has to be a location in its own right rather than relying on project-id
    inference, because the entity in the path is not always a project: a file
    uploaded against a sequencing run, sample or QC record is stored under that
    entity's UUID, and no project id appears anywhere in the key. Inference
    alone would refuse those, and -- since the signing rule is also applied to
    the upload path -- would have refused the *writes* that create them.

    That is not hypothetical. It was caught by the test suite while adding this
    rule: production's storage root is a third bucket, so a may_sign check built
    only on the data and results buckets rejected every upload.

    Tried last, after project resolution, so a stored file that *does* name a
    project resolves strictly through it and keeps that project's restriction.
    """
    root = _storage_root()
    if not root:
        return False
    target = _normalise(uri)
    return target == root or target.startswith(root + "/")


def _unresolved(session: Session, uri: str, origin: Origin) -> FileScope:
    """
    The terminal case, with the run-folder opening applied.

    Deliberately reached only *after* every project-resolving strategy has
    failed. Checking the run folder earlier would let it override a
    `restricted` project for any file that happens to sit under a run
    folder, which would make the restriction unenforceable exactly where raw
    data lives. Restriction first, opening second.
    """
    if _under_a_run_folder(session, uri):
        return FileScope(frozenset(), "run-folder", open_to_authenticated=True)
    if _under_the_file_store(session, uri):
        return FileScope(frozenset(), "file-store", open_to_authenticated=True)
    return FileScope(frozenset(), origin)


def is_wellformed(uri: str, *, require_key: bool = True) -> bool:
    """
    Does this look like an S3 location at all?

    Used to keep the location rule from answering the wrong question. A caller
    who sends `""`, `not-a-uri` or `s3://` has made a *malformed request*, and
    400 says so; answering 403 would tell them they lack access to something
    that is not a location. The guards let a malformed URI through to the
    handler's own validation and reserve the refusal for URIs that are well
    formed and simply not ours.

    `require_key` is the difference between the two callers, and it matters.
    Signing needs an object, so `s3://bucket` alone is malformed there. Listing
    does not: `s3://bucket/` is a perfectly well-formed request to enumerate a
    whole bucket, and it has to reach the location check rather than slip
    through as a malformed one -- otherwise dropping the key would be enough to
    enumerate any bucket the API can read, which is the hole this rule exists to
    close.
    """
    if not uri or not uri.startswith("s3://"):
        return False
    rest = uri[len("s3://"):]
    bucket, _, key = rest.partition("/")
    if not bucket:
        return False
    return bool(key.strip("/")) if require_key else True


def may_sign(session: Session, uri: str) -> bool:
    """
    May the platform hand out S3 credentials for this URI at all?

    Three locations qualify, and nothing else: a project, a registered run
    folder, or a registered vendor inbound prefix -- the last two reached
    through `scope_for_uri`, which resolves vendor paths to their project and
    run-folder paths to an open scope.

    This is a property of the *location*, not of the caller, so there is no role
    that overrides it and superuser does not bypass it. That is the point:
    `generate_presigned_url` signs whatever bucket and key it is handed, with no
    allowlist of its own, so an allowlist an administrator can step outside is
    not an allowlist. Previously the equivalent protection was "an unresolved
    URI requires global file:download", which four roles and every superuser
    satisfied.

    Authorisation is a separate question answered afterwards: a signable URI in
    a *restricted* project still requires membership.
    """
    scope = scope_for_uri(session, uri)
    return scope.resolved or scope.open_to_authenticated


def scope_for_uri(session: Session, uri: str) -> FileScope:
    """
    Which projects govern this URI. See the module docstring for the policy.

    Costs at most three indexed queries, and short-circuits before the run join
    whenever a direct association exists — which is the common case.
    """
    file_ids = _file_ids(session, uri)
    if not file_ids:
        inferred = _project_from_path(session, uri)
        if inferred:
            return FileScope(frozenset(inferred), "path")
        return _unresolved(session, uri, "unregistered")

    direct = _projects_direct(session, file_ids)
    if direct:
        origin: Origin = "project" if session.exec(
            select(FileProject.id).where(FileProject.file_id.in_(file_ids)).limit(1)
        ).first() else "sample"
        return FileScope(frozenset(direct), origin)

    via_run = _projects_via_run(session, file_ids)
    if via_run:
        return FileScope(frozenset(via_run), "run")

    # Registered but associated with nothing: fall through to the path, same as
    # an unregistered URI. A File row with no associations tells us no more about
    # ownership than no File row at all.
    inferred = _project_from_path(session, uri)
    if inferred:
        return FileScope(frozenset(inferred), "path")

    return _unresolved(session, uri, "unassociated")
