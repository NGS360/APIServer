#!/usr/bin/env python3
"""Backfill sample-to-file associations for a project via the API.

Given files and the samples they belong to, calls the Files API to create:
  - File records (if not already present for that URI)
  - FileProject + FileSample associations

The (file, sample) pairs come from one of two sources:

  1. --s3-uri: scan an S3 prefix and parse a sample name out of each filename
     using Illumina-style conventions.
  2. --mapping-file: read an explicit two-column "sample_id,uri" CSV/TSV.

Usage (scan S3 and infer sample names from filenames):
    python3 scripts/backfill_sample_files.py \
        --project-id P-20260101-0001 \
        --s3-uri s3://<bucket>/P-20260101-0001/<run_folder>/ \
        --api-url http://localhost:8000 \
        [--api-key <key>] \
        [--dry-run] \
        [--create-missing-samples] \
        [--file-extensions .fastq.gz .bam] \
        [--source "backfill-script"]

Usage (explicit sample_id,uri mapping -- one row per file):
    python3 scripts/backfill_sample_files.py \
        --project-id P-20260101-0001 \
        --mapping-file sample_files.csv \
        --api-url http://localhost:8000 \
        [--api-key <key>] [--dry-run] [--create-missing-samples]

Use --mapping-file when filenames do not encode the sample, or when the
file→sample relationship is not one filename per sample. For example an NCBI
BioSample can span several SRA runs, so several FASTQ URIs map to the same
sample -- just repeat the sample_id on multiple rows:

    sample_id,uri
    SAMN0001,s3://bucket/SRR100_1.fastq.gz
    SAMN0001,s3://bucket/SRR100_2.fastq.gz
    SAMN0001,s3://bucket/SRR200_1.fastq.gz
    SAMN0002,s3://bucket/SRR300_1.fastq.gz

The header row is optional, a tab delimiter (TSV) is accepted, and blank lines
and lines beginning with '#' are ignored.

In mapping mode every URI is verified against S3 with a head_object before any
record is created (even under --dry-run) -- a URI that does not exist is
reported and skipped rather than turned into a record pointing at nothing. The
object's real size and S3 ETag are read from that call and stored on the file
record. URIs must therefore be s3:// (the records are created with
storage_backend=S3), and the caller needs s3:GetObject on them.

When scanning S3, the script parses sample names from filenames using standard
Illumina demux naming: <SampleID>_S<number>_L<lane>_R<read>_001.fastq.gz

It can also handle simpler patterns like <SampleID>_R1.fastq.gz, SRA/ENA
read-pair naming <SampleID>_1.fastq.gz / <SampleID>_2.fastq.gz, or
<SampleID>.bam. See --help for customization options.

By default a file whose parsed sample name is not registered in the project is
reported and skipped. --create-missing-samples registers those names first, so
their files can be attached -- see register_samples() for why it does that
explicitly rather than letting the Files API create the samples for it.

Auth: creating file records needs none (POST /api/v1/files is unauthenticated),
but --create-missing-samples calls POST /projects/{id}/samples/bulk, which
requires sample:create on the project or a superuser. The token is read from
$NGS360_AUTHTOKEN unless --api-key is given, and is sent as a bearer token --
api/auth/deps.py reads Authorization and detects API keys by their ngs360_
prefix, so the X-API-Key header this script used to send was silently ignored.
"""

import argparse
import csv
import os
import re
import boto3
import requests
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# S3 helpers
# ---------------------------------------------------------------------------


def parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    """Parse s3://bucket/prefix into (bucket, prefix)."""
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {s3_uri}")
    without_scheme = s3_uri[5:]
    parts = without_scheme.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix


def list_s3_objects(
    bucket: str,
    prefix: str,
    extensions: list[str] | None = None,
) -> list[dict]:
    """
    List all objects under bucket/prefix.

    Returns list of dicts with keys: 'key', 'size', 'uri'.
    Optionally filters by file extension.
    """
    s3 = boto3.client("s3")
    objects = []

    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    for page in pages:
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Skip "directory" markers
            if key.endswith("/"):
                continue
            # Extension filter
            if extensions:
                if not any(key.endswith(ext) for ext in extensions):
                    continue
            objects.append({
                "key": key,
                "size": obj.get("Size"),
                "uri": f"s3://{bucket}/{key}",
            })

    return objects


# ---------------------------------------------------------------------------
# Filename → sample_id parsing
# ---------------------------------------------------------------------------

# Illumina BCL Convert / bcl2fastq pattern:
#   <SampleID>_S<number>[_L<lane>]_(R|I)<read>_001.fastq.gz
# Lane is optional (--no-lane-splitting), read can be R1/R2/I1/I2.
# Uses a greedy match for sample_id up to the LAST _S\d+ occurrence
# to handle sample names that contain _S or _R.
ILLUMINA_PATTERN = re.compile(
    r"^(?P<sample_id>.+)_S\d+(?:_L\d+)?_[RI][12]_\d+\.fastq\.gz$"
)

# Simpler patterns: <SampleID>_R1.fastq.gz or <SampleID>.R1.fastq.gz
SIMPLE_READ_PATTERN = re.compile(
    r"^(?P<sample_id>.+?)[._]R[12]\.fastq\.gz$"
)

# SRA / ENA read-pair naming: <SampleID>_1.fastq.gz or <SampleID>_2.fastq.gz
# (fasterq-dump / ENA downloads use a bare _1/_2 rather than _R1/_R2). Must be
# tried before GENERIC_PATTERN so the _1/_2 read suffix is stripped rather than
# folded into the sample name (which would split a pair into two "samples").
SRA_READ_PATTERN = re.compile(
    r"^(?P<sample_id>.+?)_[12]\.fastq\.gz$"
)

# Generic: just strip extension(s)
GENERIC_PATTERN = re.compile(
    r"^(?P<sample_id>.+?)"
    r"(?:\.fastq\.gz|\.fq\.gz|\.bam|\.cram|\.vcf\.gz)$"
)


def extract_sample_id_from_filename(filename: str) -> str | None:
    """
    Attempt to extract a sample_id from a filename using known patterns.

    Tries patterns in order of specificity:
    1. Illumina demux naming
    2. Simple read-pair naming (_R1/_R2)
    3. SRA/ENA read-pair naming (_1/_2)
    4. Generic extension stripping
    """
    for pattern in [
        ILLUMINA_PATTERN,
        SIMPLE_READ_PATTERN,
        SRA_READ_PATTERN,
        GENERIC_PATTERN,
    ]:
        match = pattern.match(filename)
        if match:
            return match.group("sample_id")
    return None


# Which read of a pair a FASTQ is, expressed as the "mate" tag the samplesheet
# builder keys on. NGSSamplesheet._files_to_mate_strings selects a file into the
# R1 (or R2) column only when the record carries tags["mate"] == "R1" (or "R2");
# a file with no mate tag is invisible to both columns. Omitting this tag is what
# produced a samplesheet whose samples were all listed but whose R1/R2 were blank.
#
# Searched (not anchored at start) so the read token is found wherever it sits in
# the name. Illumina _R1/_R2 is tried before the bare SRA/ENA _1/_2 so an Illumina
# name is not misread by the looser pattern. The .gz is optional: the pipeline
# accepts uncompressed .fastq/.fq too, and an untagged one would be just as
# invisible to the samplesheet. One processing-step word may sit between the read
# token and the extension (<sample>_1.clipped.fastq.gz, as some vendors deliver);
# without it such a pair falls through to the single-end rule below and both
# mates are tagged R1.
_STEP = r"(?:\.[A-Za-z]+)?"
MATE_PATTERNS = [
    # Illumina: _R1_001.fastq.gz, _R1.fastq.gz, etc.
    re.compile(rf"_R(?P<read>[12])(?:_\d+)?{_STEP}\.(?:fastq|fq)(?:\.gz)?$"),
    # Dot-delimited: <sample>.R1.fastq.gz
    re.compile(rf"\.R(?P<read>[12]){_STEP}\.(?:fastq|fq)(?:\.gz)?$"),
    # SRA / ENA read-pair naming: <sample>_1.fastq.gz / _2.fastq.gz
    re.compile(rf"_(?P<read>[12]){_STEP}\.(?:fastq|fq)(?:\.gz)?$"),
]


# A FASTQ with no read token in its name is single-end, and single-end reads go
# in the R1 column -- so it still gets a mate tag, just R1. Only a non-FASTQ file
# (e.g. a BAM) falls through to no tag, which is correct: it has no mate column.
FASTQ_SUFFIXES = (".fastq.gz", ".fq.gz", ".fastq", ".fq")


def extract_mate_from_filename(filename: str) -> str | None:
    """
    Return the "mate" tag for a FASTQ: "R1"/"R2" for a read-pair, "R1" for a
    single-end FASTQ, or None for a non-FASTQ file (which has no mate column).
    """
    for pattern in MATE_PATTERNS:
        match = pattern.search(filename)
        if match:
            return f"R{match.group('read')}"
    if filename.endswith(FASTQ_SUFFIXES):
        return "R1"
    return None


# ---------------------------------------------------------------------------
# Explicit sample_id → file mapping
# ---------------------------------------------------------------------------

# S3 verification is one HeadObject per URI, so a large mapping can spend
# minutes in verify_s3_objects with no output. Reprint a progress counter every
# this many URIs so the run does not look hung.
VERIFY_PROGRESS_INTERVAL = 50

# Second-column values that indicate a header row rather than a URI, so the
# header can be dropped without being reported as a malformed data row.
_HEADER_URI_TOKENS = {"uri", "url", "fastq", "fastq_url", "file", "path"}


def load_mapping(
    path: str,
) -> tuple[list[tuple[dict, str]], list[tuple[str, str]]]:
    """
    Read a two-column "sample_id,uri" mapping (CSV or TSV).

    Each row maps one file URI to one sample. Repeating a sample_id across rows
    is expected -- that is the point of this mode: an NCBI BioSample can span
    several SRA runs, so several FASTQ URIs attach to the same sample.

    The delimiter is tab if any tab is present, otherwise comma. Blank lines and
    lines starting with '#' are ignored, as is a single header row whose second
    column is a header word rather than a URI.

    Returns (parsed_objects, malformed), mirroring the S3 path so the caller can
    treat both sources the same: parsed_objects is a list of (obj, sample_id)
    where obj carries 'key'/'size'/'uri' (size is None -- the mapping does not
    know it, and the Files API treats size as optional), and malformed is a list
    of (row_text, reason) for rows that could not be read.
    """
    parsed_objects: list[tuple[dict, str]] = []
    malformed: list[tuple[str, str]] = []

    with open(path, newline="") as fh:
        sample = fh.read(8192)
        fh.seek(0)
        delimiter = "\t" if "\t" in sample else ","
        for row in csv.reader(fh, delimiter=delimiter):
            if not row:
                continue
            sample_id = row[0].strip()
            if not sample_id or sample_id.startswith("#"):
                continue
            if len(row) < 2 or not row[1].strip():
                malformed.append(
                    (delimiter.join(row), "expected 2 columns: sample_id,uri")
                )
                continue
            uri = row[1].strip()
            if "://" not in uri:
                # A header row (sample_id,uri) or a bad value. Skip a header
                # word silently; report anything else as malformed.
                if uri.lower() not in _HEADER_URI_TOKENS:
                    malformed.append((uri, "value is not a URI (missing '://')"))
                continue
            parsed_objects.append(
                ({"key": uri, "size": None, "uri": uri}, sample_id)
            )

    return parsed_objects, malformed


def verify_s3_objects(
    parsed_objects: list[tuple[dict, str]],
) -> tuple[list[tuple[dict, str]], list[tuple[str, str]]]:
    """
    HeadObject every mapping URI, confirming it exists before a record is made.

    Unlike the S3-scan path, a mapping file is just text -- a typo'd or
    since-deleted path would otherwise become a File record pointing at nothing.
    For each object that exists this fills obj['size'] and obj['etag'] from the
    HeadObject response (the mapping does not carry them), so the record stores
    the real size and S3 ETag rather than nulls.

    Returns (verified, missing): verified is the (obj, sample_id) pairs whose
    object exists (with size/etag populated), and missing is (uri, reason) for
    the rest.
    """
    s3 = boto3.client("s3")
    verified: list[tuple[dict, str]] = []
    missing: list[tuple[str, str]] = []
    total = len(parsed_objects)

    for idx, (obj, sample_id) in enumerate(parsed_objects, 1):
        # Progress ticker (in-place). Updated before the HeadObject for this
        # item, so it reads as "how far along" rather than "how many finished".
        if idx % VERIFY_PROGRESS_INTERVAL == 0 or idx == total:
            print(f"\r  Checking {idx}/{total} URIs...", end="", flush=True)

        uri = obj["uri"]
        try:
            bucket, key = parse_s3_uri(uri)
        except ValueError:
            missing.append((uri, "not an s3:// URI (cannot verify)"))
            continue
        if not key:
            missing.append((uri, "s3:// URI has no object key"))
            continue

        try:
            head = s3.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                reason = "not found in S3"
            else:
                reason = f"S3 error {code or type(e).__name__}"
            missing.append((uri, reason))
            continue

        obj["size"] = head.get("ContentLength")
        # S3 returns the ETag wrapped in literal double quotes; store the bare
        # value. For multipart uploads this is "<md5>-<partcount>", not a plain
        # MD5, but it is still the object's S3 ETag -- recorded as such.
        obj["etag"] = (head.get("ETag") or "").strip('"') or None
        verified.append((obj, sample_id))

    if total:
        print()  # end the in-place progress line before the caller prints more

    return verified, missing


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------


def make_session(api_key: str | None = None) -> requests.Session:
    """
    Create a requests session with optional auth.

    Bearer, not X-API-Key: get_current_user reads the Authorization header for
    both JWTs and ngs360_-prefixed API keys, and nothing in the app looks at
    X-API-Key, so a key sent that way authenticates as nobody.
    """
    sess = requests.Session()
    sess.headers["Content-Type"] = "application/json"
    if api_key:
        sess.headers["Authorization"] = f"Bearer {api_key}"
    return sess


def get_project_samples(
    http: requests.Session,
    base_url: str,
    project_id: str,
) -> dict[str, str]:
    """
    Fetch all samples for a project via the API.
    Returns dict mapping sample_id (string) → sample_id.
    (We only need to know which sample_ids exist.)
    """
    samples: dict[str, str] = {}
    skip = 0
    limit = 1000

    while True:
        url = (
            f"{base_url}/api/v1/projects/{project_id}/samples"
            f"?skip={skip}&limit={limit}"
        )
        resp = http.get(url)
        resp.raise_for_status()
        data = resp.json()

        for item in data["data"]:
            samples[item["sample_id"]] = item["sample_id"]

        if not data.get("has_next", False):
            break
        skip += limit

    return samples


def register_samples(
    http: requests.Session,
    base_url: str,
    project_id: str,
    sample_names: list[str],
    batch_size: int = 200,
) -> tuple[dict, set[str]]:
    """
    Register samples whose names were parsed out of filenames.

    Returns (stats, confirmed) where `confirmed` is the names that now exist --
    only those get files attached, so a batch that fails costs its own samples'
    files rather than the whole run.

    Goes through POST /projects/{id}/samples/bulk rather than letting the Files
    API create the samples implicitly. Both produce a Sample row, but the implicit
    path runs through resolve_or_create_sample, which tags the row
    auto_created_stub and deliberately does not index it -- the sample would own
    files while staying invisible to search until somebody reindexed. The bulk
    endpoint indexes what it creates, and treats a name that already exists as
    existing rather than as an error, so re-running is safe.

    Batched because each request is one all-or-nothing transaction: a failure
    rolls back only its own batch, and earlier batches stand.
    """
    stats = {"samples_created": 0, "samples_existing": 0, "errors": 0}
    confirmed: set[str] = set()

    for start in range(0, len(sample_names), batch_size):
        batch = sample_names[start:start + batch_size]
        resp = http.post(
            f"{base_url}/api/v1/projects/{project_id}/samples/bulk",
            json={"samples": [{"sample_id": name} for name in batch]},
        )

        if resp.status_code not in (200, 201):
            stats["errors"] += 1
            print(
                f"  ERROR registering {len(batch)} sample(s) "
                f"({batch[0]} .. {batch[-1]}): {resp.status_code} {resp.text[:300]}"
            )
            continue

        body = resp.json()
        stats["samples_created"] += body.get("samples_created", 0)
        stats["samples_existing"] += body.get("samples_existing", 0)
        confirmed.update(item["sample_id"] for item in body.get("items", []))
        print(
            f"  [{start + len(batch)}/{len(sample_names)}] "
            f"{body.get('samples_created', 0)} created, "
            f"{body.get('samples_existing', 0)} already existed"
        )

    return stats, confirmed


def check_file_exists(
    http: requests.Session,
    base_url: str,
    uri: str,
) -> bool:
    """Check if a file record already exists for this URI."""
    url = f"{base_url}/api/v1/files"
    resp = http.get(url, params={"uri": uri})
    if resp.status_code == 404:
        return False
    resp.raise_for_status()
    data = resp.json()
    # FilesPublic has 'data' list
    return len(data.get("data", [])) > 0


def create_file_record(
    http: requests.Session,
    base_url: str,
    uri: str,
    project_id: str,
    sample_name: str,
    size: int | None = None,
    source: str = "backfill-script",
    hashes: dict[str, str] | None = None,
    tags: dict[str, str] | None = None,
) -> dict:
    """
    Create a file record via POST /api/v1/files.

    Associates the file with both the project and the sample. `hashes` is a
    {algorithm: value} map (e.g. {"etag": "..."}) stored as FileHash rows.
    `tags` is a {key: value} map (e.g. {"mate": "R1"}) stored as FileTag rows --
    the samplesheet builder reads tags["mate"] to place a FASTQ in the R1/R2
    column, so a file created without it is invisible to that column.
    """
    payload = {
        "uri": uri,
        "project_id": project_id,
        "source": source,
        "storage_backend": "S3",
        "samples": [{"sample_name": sample_name}],
    }
    if size is not None:
        payload["size"] = size
    if hashes:
        payload["hashes"] = hashes
    if tags:
        payload["tags"] = tags

    # Derive original_filename from URI
    filename = uri.rsplit("/", 1)[-1]
    payload["original_filename"] = filename

    resp = http.post(f"{base_url}/api/v1/files", json=payload)
    if resp.status_code == 409:
        # File already exists (versioning conflict) — not an error
        return {"skipped": True, "detail": resp.json()}
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main backfill logic
# ---------------------------------------------------------------------------

# Per-file "created" lines get unreadable at scale (thousands of files), so we
# print the first PER_FILE_PRINT_LIMIT in full and then switch to an in-place
# progress counter, refreshed every CREATE_PROGRESS_INTERVAL files (like the S3
# phase) so a large run does not look hung. The summary still totals everything,
# and errors are always printed regardless of these caps.
PER_FILE_PRINT_LIMIT = 100
CREATE_PROGRESS_INTERVAL = 50


def backfill(
    project_id: str,
    api_url: str,
    s3_uri: str | None = None,
    mapping_file: str | None = None,
    api_key: str | None = None,
    dry_run: bool = True,
    extensions: list[str] | None = None,
    source: str = "backfill-script",
    create_missing_samples: bool = False,
    sample_batch_size: int = 200,
) -> None:
    """
    Build a set of (file, sample) pairs -- either by scanning an S3 prefix and
    parsing sample names from filenames, or from an explicit --mapping-file --
    then create the missing file/association records via the API.
    """
    print(
        f"{'[DRY RUN] ' if dry_run else ''}"
        f"Backfilling sample-file associations"
    )
    print(f"  Project:    {project_id}")
    if mapping_file:
        print(f"  Mapping:    {mapping_file}")
    else:
        bucket, prefix = parse_s3_uri(s3_uri)
        print(f"  S3 URI:     s3://{bucket}/{prefix}")
        print(f"  Extensions: {extensions or ['all']}")
    print(f"  API URL:    {api_url}")
    sample_mode = (
        "register names not already in the project"
        if create_missing_samples
        else "must already exist (--create-missing-samples to add)"
    )
    print(f"  Samples:    {sample_mode}")
    print()

    stats = {
        "samples_created": 0,
        "samples_existing": 0,
        "files_created": 0,
        "files_already_existed": 0,
        "unmatched_files": 0,
        "errors": 0,
    }
    unmatched: list[tuple[str, str | None]] = []

    # -- Build the (file, sample_id) work set up front, so the set of sample
    #    names that need registering is known before anything is written.
    #    Either read it straight from the mapping file, or scan S3 and parse a
    #    sample name out of each filename.
    if mapping_file:
        print(f"Reading mapping file {mapping_file}...")
        parsed_objects, malformed = load_mapping(mapping_file)
        for row_text, reason in malformed:
            stats["unmatched_files"] += 1
            unmatched.append((row_text, reason))
        print(
            f"  {len(parsed_objects)} file->sample row(s), "
            f"{len(malformed)} unreadable row(s)."
        )
        print()

        # Confirm each URI actually exists in S3 (and capture its size + etag)
        # before creating records. Runs even in --dry-run: it is a read-only
        # check, and knowing which URIs are missing is the point of the preview.
        print("Verifying URIs against S3 (head_object)...")
        parsed_objects, missing = verify_s3_objects(parsed_objects)
        for uri, reason in missing:
            stats["unmatched_files"] += 1
            unmatched.append((uri, reason))
        print(
            f"  {len(parsed_objects)} verified, "
            f"{len(missing)} missing/unreadable."
        )
        print()
    else:
        print("Scanning S3...")
        objects = list_s3_objects(bucket, prefix, extensions)
        print(f"  Found {len(objects)} file(s) matching criteria.")
        print()

        parsed_objects = []
        for obj in objects:
            filename = obj["key"].split("/")[-1]
            parsed_sample_id = extract_sample_id_from_filename(filename)
            if parsed_sample_id is None:
                stats["unmatched_files"] += 1
                unmatched.append((filename, "could not parse sample_id"))
                continue
            parsed_objects.append((obj, parsed_sample_id))

    if not parsed_objects and not unmatched:
        print("Nothing to do.")
        return

    # -- Fetch samples from API --
    http = make_session(api_key)
    print("Fetching samples from API...")
    samples_map = get_project_samples(http, api_url, project_id)
    print(f"  {len(samples_map)} sample(s) in project.")
    print()

    unregistered = sorted(
        {name for _, name in parsed_objects if name not in samples_map}
    )
    if unregistered and create_missing_samples:
        print(
            f"{len(unregistered)} sample name(s) are not registered in "
            f"{project_id}:"
        )
        for name in unregistered[:20]:
            print(f"    - {name}")
        if len(unregistered) > 20:
            print(f"    ... and {len(unregistered) - 20} more")

        if dry_run:
            stats["samples_created"] = len(unregistered)
            samples_map.update({name: name for name in unregistered})
        else:
            print("Registering them...")
            sample_stats, confirmed = register_samples(
                http=http,
                base_url=api_url,
                project_id=project_id,
                sample_names=unregistered,
                batch_size=sample_batch_size,
            )
            stats["samples_created"] = sample_stats["samples_created"]
            stats["samples_existing"] = sample_stats["samples_existing"]
            stats["errors"] += sample_stats["errors"]
            # Only names the API confirmed get files; the rest fall through to
            # the unmatched report below rather than having files attached to
            # a sample that does not exist.
            samples_map.update({name: name for name in confirmed})
        print()
    elif unregistered:
        skipped = sum(1 for _, name in parsed_objects if name not in samples_map)
        print(
            f"{len(unregistered)} sample name(s) are not registered, so "
            f"{skipped} file(s) will be skipped. Re-run with "
            f"--create-missing-samples to register them."
        )
        print()

    work = []
    for obj, parsed_sample_id in parsed_objects:
        if parsed_sample_id in samples_map:
            work.append((obj, parsed_sample_id))
        else:
            stats["unmatched_files"] += 1
            unmatched.append((
                obj["key"].split("/")[-1],
                f"sample '{parsed_sample_id}' not registered in project",
            ))

    def report_file(message: str, printed: int) -> int:
        """
        Print a per-file line and return the new printed-line count.

        Callers guard on PER_FILE_PRINT_LIMIT and skip the call once the cap is
        reached, so this only ever runs while there is still room to print.
        """
        print(message)
        printed += 1
        if printed == PER_FILE_PRINT_LIMIT:
            print(
                f"  ... {PER_FILE_PRINT_LIMIT} shown; switching to a progress "
                f"counter (see summary below)."
            )
        return printed

    printed = 0
    for i, (obj, parsed_sample_id) in enumerate(work, 1):
        # Once the detailed listing is capped, show an in-place progress ticker
        # instead so a large run does not look hung.
        if printed >= PER_FILE_PRINT_LIMIT and (
            i % CREATE_PROGRESS_INTERVAL == 0 or i == len(work)
        ):
            print(f"\r  {i}/{len(work)} files processed...", end="", flush=True)

        uri = obj["uri"]
        filename = obj["key"].split("/")[-1]
        mate = extract_mate_from_filename(filename)

        # Check if file already exists
        try:
            exists = check_file_exists(http, api_url, uri)
        except requests.HTTPError as e:
            print(f"  ERROR checking {uri}: {e}")
            stats["errors"] += 1
            continue

        if exists:
            stats["files_already_existed"] += 1
            continue

        # Create file record (with sample association)
        if dry_run:
            stats["files_created"] += 1
            if printed < PER_FILE_PRINT_LIMIT:
                printed = report_file(
                    f"  [{i}/{len(work)}] Would create: "
                    f"{filename} → {parsed_sample_id}"
                    f"{f' [{mate}]' if mate else ''}",
                    printed,
                )
        else:
            try:
                etag = obj.get("etag")
                result = create_file_record(
                    http=http,
                    base_url=api_url,
                    uri=uri,
                    project_id=project_id,
                    sample_name=parsed_sample_id,
                    size=obj["size"],
                    source=source,
                    hashes={"etag": etag} if etag else None,
                    tags={"mate": mate} if mate else None,
                )
                if result.get("skipped"):
                    stats["files_already_existed"] += 1
                else:
                    stats["files_created"] += 1
                    if printed < PER_FILE_PRINT_LIMIT:
                        printed = report_file(
                            f"  [{i}/{len(work)}] Created: "
                            f"{filename} → {parsed_sample_id}",
                            printed,
                        )
            except requests.HTTPError as e:
                print(f"  ERROR creating {uri}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    print(f"    Response: {e.response.text}")
                stats["errors"] += 1

    if printed >= PER_FILE_PRINT_LIMIT:
        print()  # end the in-place progress line before the summary

    # -- Summary --
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if create_missing_samples:
        print(f"  Samples registered:         {stats['samples_created']}")
        print(f"  Samples already existed:    {stats['samples_existing']}")
    print(f"  Files created:              {stats['files_created']}")
    print(f"  Files already existed:      {stats['files_already_existed']}")
    print(f"  Unmatched files (no sample):{stats['unmatched_files']}")
    print(f"  Errors:                     {stats['errors']}")

    if dry_run:
        print("\n  [DRY RUN] No changes were made.")

    if unmatched:
        print(f"\n  Unmatched files ({len(unmatched)}):")
        for label, reason in unmatched[:20]:
            print(f"    - {label}: {reason}")
        if len(unmatched) > 20:
            print(f"    ... and {len(unmatched) - 20} more")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill sample-to-file associations "
            "from S3 for a project via the API."
        )
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Project ID (e.g., P-20260101-0001)",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--s3-uri",
        help=(
            "S3 URI prefix to scan, inferring sample names from filenames "
            "(e.g., s3://bucket/project/run_folder/). Mutually exclusive with "
            "--mapping-file."
        ),
    )
    source_group.add_argument(
        "--mapping-file",
        help=(
            "Path to a two-column 'sample_id,uri' CSV/TSV giving the "
            "file->sample mapping explicitly (one row per file; repeat a "
            "sample_id to attach several files to it). Mutually exclusive "
            "with --s3-uri."
        ),
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Base URL of the API server (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("NGS360_AUTHTOKEN"),
        help=(
            "JWT or ngs360_ API key, sent as a bearer token. Defaults to "
            "$NGS360_AUTHTOKEN. Only needed for --create-missing-samples; "
            "creating file records is unauthenticated."
        ),
    )
    parser.add_argument(
        "--create-missing-samples",
        action="store_true",
        help=(
            "Register sample names parsed from filenames that do not exist in the "
            "project yet, instead of skipping their files. Requires sample:create "
            "on the project (or superuser)."
        ),
    )
    parser.add_argument(
        "--sample-batch-size",
        type=int,
        default=200,
        help=(
            "Samples per bulk-registration request (default: 200). Each request is "
            "one all-or-nothing transaction."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be done without making API calls",
    )
    parser.add_argument(
        "--file-extensions",
        nargs="*",
        default=[".fastq.gz"],
        help=(
            "File extensions to include (default: .fastq.gz). "
            "Use --file-extensions .fastq.gz .bam .cram for multiple."
        ),
    )
    parser.add_argument(
        "--source",
        default="backfill-script",
        help="Value for File.source field (default: 'backfill-script')",
    )
    args = parser.parse_args()

    # Fail here rather than after the S3 scan and the per-file work: registration
    # is authenticated, so without a token every sample would 401 and every file
    # that needed one would be skipped -- a run that looks like it worked.
    if args.create_missing_samples and not args.api_key and not args.dry_run:
        parser.error(
            "--create-missing-samples needs a token: pass --api-key or set "
            "$NGS360_AUTHTOKEN (sample:create on the project, or superuser)"
        )

    return args


if __name__ == "__main__":
    args = parse_args()
    backfill(
        project_id=args.project_id,
        s3_uri=args.s3_uri,
        mapping_file=args.mapping_file,
        api_url=args.api_url.rstrip("/"),
        api_key=args.api_key,
        dry_run=args.dry_run,
        extensions=args.file_extensions,
        source=args.source,
        create_missing_samples=args.create_missing_samples,
        sample_batch_size=args.sample_batch_size,
    )
