# File registration and download resolution

How `GET /files/download-url` decides, what a pipeline must register for its
outputs to be downloadable, and what it would take to resolve run-level
artifacts by path instead.

Companion to the "Downloads: open by default, restricted by exception" section
of [RBAC.md](RBAC.md). That section states the policy; this one is about the
*record* the policy reads.

## The problem, measured

`require_file_download` (`api/files/routes.py`) has three branches:

| URI resolves to | Requires |
|---|---|
| a project, unrestricted | nothing — allowed |
| a project, `download_restricted` | `file:download` on that project |
| nothing | **global** `file:download` |

No project in production sets `download_restricted`, so the middle branch is
currently unreachable and every refusal is the third one. Global
`file:download` is carried only by `lab_manager`, `auditor`, `admin` and
superusers, so an ordinary user hitting an unresolvable URI is refused.

A week of `/files/download-url` traffic, grouped by the resolution origin the
access log already records:

| Requests | Decision | Origin |
|---|---|---|
| 421 | allow | `file via path, 1 project(s)` |
| 17 | allow | `file via project, 1 project(s)` |
| 13 | allow | `file via unregistered, 0 project(s)` |
| **51** | **would_deny** | `file via unregistered, 0 project(s)` |

Three things to read off that table:

1. **The refusals and 13 of the allowances are the same requests.** Same files,
   same unresolvable URIs; the 13 succeeded only because those callers happened
   to hold a global grant. Nothing about the file differed.
2. **96% of successful downloads are granted by path inference** — the
   last-resort strategy that `api/files/scope.py` describes as "access granted
   by convention rather than by record" and says "should trend towards zero". It
   is instead the dominant path, which means registration is not happening
   broadly.
3. **The refused URIs are demux QC reports**, under
   `<raw-bucket>/illumina/<run-folder>/Stats/` and `.../Reports/html/`, requested
   from the run samplesheet page in the UI. They carry a run folder name and no
   project id, and they live outside the two buckets inference is confined to.

The policy already covers this case. `api/files/scope.py` says plainly that
"demux statistics and samplesheets belong to the run rather than to one project"
and implements a run fallback to permit exactly this traffic. The resolver simply
cannot see these files, for two independent reasons — they are not registered,
and their bucket is not one inference may read.

## Part 1 — The registration contract

What a pipeline must do so that a file it writes is resolvable. This activates
the **run fallback**, which already exists and is already approved policy.

> **Current state: `filesequencingrun` has zero rows platform-wide.** The run
> fallback has never resolved anything in production. It is not broken — nothing
> has ever registered a file against a run.

### The call

```http
POST /api/v1/files
Authorization: Bearer <service-account key>
Content-Type: application/json

{
  "uri": "s3://<raw-bucket>/illumina/<run-folder>/Stats/Stats.json",
  "sequencing_run_id": "<uuid of the run>",
  "size": 16823,
  "created_on": "2026-09-30T04:12:08Z",
  "created_by": "<pipeline or operator>",
  "source": "demux",
  "storage_backend": "S3",
  "tags": {"type": "demux-stats"}
}
```

### Field rules

| Field | Required | Notes |
|---|---|---|
| `uri` | yes | Max 512 chars. Not unique by itself — see idempotency below. |
| `sequencing_run_id` | yes, for run artifacts | The run's **UUID**, not its run folder name. `FileCreate` validates that the run exists and rejects unknown ids. |
| `created_on` | recommended | Defaults to now. Part of the uniqueness key, so supplying the artifact's real timestamp is what makes re-runs idempotent. |
| `size`, `source`, `storage_backend`, `tags`, `hashes` | optional | `size` is a BIGINT, so files over 2 GB are fine. |
| `created_by` | optional | An "on behalf of" claim, validated against known usernames. The authenticated caller is recorded separately as `submitted_by` and cannot be set from the request. |
| `project_id` | **no** | Do not set it for run-level artifacts. Direct project association resolves *strictly* and takes precedence over the run fallback, so naming one project for a flowcell artifact would narrow access to that project instead of widening it to the run's projects. This ordering is deliberate; see the `scope.py` module docstring. |

`FileCreate` sets `extra="forbid"`, so an unexpected field is a 422 rather than
a silently ignored key. At least one entity association is required — a file
with none is rejected as an orphan.

### Getting the run UUID

`sequencing_run_id` is the primary key of `sequencingrun`, not the run folder
name. Resolve it first:

```http
GET /api/v1/runs/{run_id}      # run_id is the run folder name, e.g. 260930_VH01208_...
```

and take `id` from the response.

### Idempotency

Uniqueness is `(uri, created_on)`, which exists to support versioning: the same
URI at a different timestamp is a new version, by design. So:

- Re-registering with the **same** `created_on` conflicts — treat a 409 as
  success-already-done, not as an error.
- Re-registering with a **new** `created_on` creates a second version. For a
  file that gets rewritten in place each demux, that is correct and wanted.
- Pass the artifact's own mtime rather than `now()`, or a retry loop will
  create a version per attempt.

### Permission

`POST /files` requires `file:create`, which the `service_account` role carries.
A pipeline already holding `service_account` needs no new grant.

### Which artifacts to register

The ones the UI links from the run page, at minimum:

- `Stats/Stats.json`, `Stats/DemultiplexingStats.xml`, `Stats/DemuxSummaryF*L*.txt`
- `Reports/html/**` — notably `laneBarcode.html`, the most-requested file
- `RunInfo.xml`, `RunParameters.xml`, `SampleSheet.csv`
- InterOp summaries, if they are ever linked

### Known gap

`FileSequencingRun` has a `role` column documented for exactly this use
(`samplesheet`, `stats`, `interop`, `runinfo`), but `FileCreate` has no field
to set it — the scalar `sequencing_run_id` is stored with a null role. Nothing
reads it today, so this does not block registration, but a pipeline that wants
to label artifacts by role cannot currently do so through the API.

## Part 2 — Option B: resolving run artifacts by path

Inference from the run folder in the path, as a parallel to the existing
project-id inference. Worth doing **in addition to** Part 1, because it covers
every historical artifact that will never be retro-registered.

The security constraint that made this questionable does not apply: the raw
instrument bucket is NGS360-owned, like the other two. Inference stays inside
data the platform itself writes.

### What it takes

1. **A new setting, `RAW_BUCKET_URI`**, naming the instrument bucket. The bucket
   name belongs in configuration, not in code — `DATA_BUCKET_URI` and
   `RESULTS_BUCKET_URI` are already settings for the same reason, and this
   repository is public.

2. **Keep the two allowlists separate.** `_OWNED_BUCKET_SETTINGS` currently
   governs *project-id* inference. The raw bucket must not join that list: its
   keys are organised by run folder, not project id, so allowing project
   inference there would match any project id that happened to appear in a path
   without meaning the file belongs to that project. Introduce a second constant
   for run inference instead:

   ```python
   _PROJECT_INFERENCE_BUCKETS = ("DATA_BUCKET_URI", "RESULTS_BUCKET_URI")
   _RUN_INFERENCE_BUCKETS = ("RAW_BUCKET_URI",)
   ```

3. **A run-folder pattern**, anchored to a path segment the way `_PROJECT_ID`
   is, so a substring inside a filename cannot be mistaken for a run:

   ```python
   _RUN_FOLDER = re.compile(r"(?:^|/)(\d{6}_[A-Za-z0-9]+_\d+_[A-Za-z0-9-]+)(?:/|$)")
   ```

   Derive it from how run folders are actually named rather than trusting this
   sketch — the `run_id` column is the authority, and ONT runs may not match the
   Illumina shape.

4. **The run must exist**, mirroring "the project must exist" in the current
   inference. A path naming an unknown run resolves to nothing; it does not
   invent a scope. Match on `sequencingrun.run_id`.

5. **Reuse `_projects_for_runs`.** Once the run is identified, resolution is the
   existing run fallback — run → its samples → their projects. No new widening
   semantics.

6. **A new `Origin` value**, e.g. `"run-path"`, so this traffic is distinguishable
   in the access log from both registered resolution and project-id inference.
   The point of recording origin is to watch convention-based access shrink; a
   new convention that reports itself as an existing one defeats that.

7. **Run inference last**, after project-id inference, for the same reason
   project association beats the run fallback: strict before permissive.

8. **Tests**, pinning: a run folder under the raw bucket resolves; the same path
   under an unowned bucket does not; an unknown run resolves to nothing; a run
   folder appearing inside a filename does not match; and project-id inference
   still does not apply to the raw bucket.

## Part 3 — The ceiling both options share, and it is the real finding

Both Part 1 and Part 2 end in the same join: run → samples → projects. If a run
reaches no project, the URI resolves to **zero** projects and the download is
still refused.

How often runs reach a project in production:

| Run age | Runs | Reaching a project |
|---|---|---|
| last 30 days | 46 | 22 (48%) |
| last 90 days | 172 | 97 (56%) |
| last 365 days | 728 | 217 (30%) |
| all time | 6,712 | 219 (3%) |

So sample-to-project association is a recent practice, and even among current
runs it holds for only about half. **Neither option fixes more than roughly half
of recent run-artifact traffic, and neither does anything for older runs.**

That is not an argument against doing them — the run in the refusal logs has 20
samples and resolves to exactly one project, so it is in the half that works.
But it means neither should be described as closing out `file:download`.

**Resolved, 2026-10-06: the second option was taken.** Run folders are open to
any authenticated caller, with no project resolved — see
[RBAC.md](RBAC.md#run-folders-are-open-to-authenticated-callers). The rule
matches a URI's parent prefixes against `sequencingrun.run_folder_uri`, so
registration rather than a bucket allowlist is the boundary, and it is evaluated
only after project resolution fails so that `download_restricted` still wins.

That closes the run-folder traffic without depending on the join above, which is
why it was preferred over Parts 1 and 2. **Both remain worth doing anyway**, for
reasons the download fix does not cover:

- registration is what makes a file *findable, versioned and attributable*, not
  merely downloadable, and `filesequencingrun` is still empty;
- 96% of successful downloads still resolve by path inference rather than by
  record, which is the figure the origin logging exists to shrink.

The remaining refusals after the run-folder change — 83 requests over 28 days —
are vendor inbound buckets shaped `.../incoming/<project-id>/...`. They carry a
project id and would resolve through existing path inference if their buckets
were recognised as owned. That is the next thing to look at.

The other half of the measurement above still stands as a data-quality problem
independent of downloads: **associating samples with projects at demux time**
would fix resolution for every strategy at once, and is the root cause of the
97%.

The "unresolved requires a global grant" rule must stay for genuinely
unresolvable URIs regardless of which path is taken: `generate_presigned_url`
signs whatever bucket and key it is handed, and that rule is what stops the
endpoint becoming an arbitrary-S3-read proxy.
