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
from api.runs.models import SampleSequencingRun
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
Origin = Literal["project", "sample", "run", "path", "unregistered", "unassociated"]


@dataclass(frozen=True)
class FileScope:
    """The projects governing a URI, and how they were arrived at."""

    project_ids: frozenset[uuid.UUID]
    origin: Origin

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
        return FileScope(frozenset(), "unregistered")

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

    return FileScope(frozenset(), "unassociated")
