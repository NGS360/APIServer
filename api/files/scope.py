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

A URI that resolves to nothing is not downloadable. That is deliberate: the
requirement is that a caller without permission on a project cannot download its
files, and "this file belongs to no project" is not evidence of permission. It is
reported distinctly from a denial so the unresolvable surface can be measured
rather than guessed at.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session, select

from api.files.models import File, FileProject, FileSample, FileSequencingRun
from api.project.models import Project
from api.runs.models import SampleSequencingRun
from api.samples.models import Sample

#: How a URI was resolved. Recorded on the access log so the mix is measurable.
Origin = Literal["project", "sample", "run", "unregistered", "unassociated"]


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


def scope_for_uri(session: Session, uri: str) -> FileScope:
    """
    Which projects govern this URI. See the module docstring for the policy.

    Costs at most three indexed queries, and short-circuits before the run join
    whenever a direct association exists — which is the common case.
    """
    file_ids = _file_ids(session, uri)
    if not file_ids:
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

    return FileScope(frozenset(), "unassociated")
