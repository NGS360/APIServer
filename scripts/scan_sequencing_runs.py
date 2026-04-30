#!/usr/bin/env python3
"""Scan S3 bucket for Illumina/ONT run folders.

Usage:
    PYTHONPATH=. python3 scripts/scan_sequencing_runs.py
        --bucket <sequencing runs bucket>
        --illumina <Illumina runs folder>
        --ont <ONT runs folder>

Output:
    List of run folders (directories) found in the bucket/prefix
"""

import argparse
import boto3
from botocore.exceptions import BotoCoreError, ClientError

import xml.etree.ElementTree as ET

from sample_sheet import SampleSheet as IlluminaSampleSheet


def parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse an S3 path into bucket and prefix.

    Args:
        s3_path: S3 path in the format s3://bucket/prefix
    Returns:
        Tuple of (bucket, prefix)
    """
    if not s3_path.startswith("s3://"):
        raise ValueError("S3 path must start with s3://")

    path_parts = s3_path[5:].split("/", 1)
    bucket = path_parts[0]
    prefix = path_parts[1] if len(path_parts) > 1 else ""
    return bucket, prefix


def get_run_folders(bucket: str, prefix: str) -> list[str]:
    """Scan the bucket/prefix for run folders and return them.

    Args:
        bucket: S3 bucket name
        prefix: S3 prefix to scan

    Returns:
        List of run folder names (with trailing slash)
    """
    s3 = boto3.client("s3")
    run_folders = []

    try:
        # Use list_objects_v2 with delimiter to get "folders"
        paginator = s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(
            Bucket=bucket,
            Prefix=prefix,
            Delimiter="/"
        )

        for page in pages:
            # CommonPrefixes contains the "folders"
            for prefix_info in page.get("CommonPrefixes", []):
                folder = prefix_info["Prefix"]
                # Extract just the folder name (remove the parent prefix)
                folder_name = folder[len(prefix):]
                run_folders.append(folder_name)

    except (ClientError, BotoCoreError) as e:
        print(f"Error scanning S3: {e}")
        return []

    return run_folders


def find_run_info_xml(s3_client, bucket: str, folder_path: str) -> str | None:
    """Find RunInfo.xml in the folder or its subfolders.

    Args:
        s3_client: Boto3 S3 client
        bucket: S3 bucket name
        folder_path: Full S3 path to the folder (with trailing slash)

    Returns:
        Full S3 path to RunInfo.xml if found, None otherwise
    """
    try:
        # First check if RunInfo.xml exists at the folder level
        runinfo_path = f"{folder_path}RunInfo.xml"
        s3_client.head_object(Bucket=bucket, Key=runinfo_path)
        return runinfo_path
    except ClientError:
        pass

    # If not found at folder level, search in subfolders
    try:
        paginator = s3_client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=folder_path)

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.endswith("RunInfo.xml"):
                    return key
    except (ClientError, BotoCoreError):
        pass

    return None


def read_run_info_xml(s3, bucket: str, key: str) -> bytes:
    # Get the RunInfo.xml file for this run folder
    get_object_kwargs = {
        "Bucket": bucket,
        "Key": key
    }
    response = s3.get_object(**get_object_kwargs)
    content = response["Body"].read()
    return content


def extract_run_info_fields(xml_bytes: bytes) -> dict:
    """
    Return run dict

    """
    root = ET.fromstring(xml_bytes)

    run_node = root.find("Run")
    if run_node is None:
        return {}
    run_info = {
        "run_id": run_node.attrib.get("Id", ""),
        "run_version": root.attrib.get("Version", ""),
        "run_number": run_node.attrib.get("Number", ""),
        "machine_id": (run_node.findtext("Instrument") or "").strip(),
        "flowcell_id": (run_node.findtext("Flowcell") or "").strip()
    }
    return run_info


def read_samplesheet(run_folder):
    try:
        sample_sheet = IlluminaSampleSheet(run_folder + "/SampleSheet.csv")
        info = {
            "experiment_name": sample_sheet.Header.get('Experiment Name', "").strip()
        }
        return info
    except Exception as e:
        print(f"  Could not read SampleSheet.csv: {e}")
        return {"experiment_name": ""}


def update_database():
    import datetime
    from sqlmodel import delete
    from api.runs.models import SequencingRun, SampleSequencingRun
    from core.db import get_session

    session = next(get_session())

    with open("run_info.txt", "r") as f:
        lines = f.readlines()
        for line in lines[1:]:  # Skip header
            parts = line.strip().split("\t")
            if len(parts) == 8:
                run_time = None
                (
                    run_id, run_date, machine_id,
                    run_number, flowcell_id,
                    experiment_name, run_folder_uri,
                    status,
                ) = parts
            else:
                (
                    run_id, run_date, machine_id,
                    run_number, flowcell_id,
                    experiment_name, run_folder_uri,
                    status, run_time,
                ) = parts

            print(f"Adding run {run_id}")

            # Run date is not in run_info correctly so we need to create it here.
            run_date = run_id.split("_")[0]
            if run_folder_uri.endswith("/"):
                run_folder_uri = run_folder_uri[:-1]

            # Convert run_date string to datetime.date object
            if len(run_date) == 6:  # YYMMDD
                run_date = datetime.datetime.strptime(run_date, "%y%m%d").date()
            elif len(run_date) == 8:  # YYYYMMDD
                run_date = datetime.datetime.strptime(run_date, "%Y%m%d").date()
            else:
                print(
                    f"  WARNING: Unrecognized run_date format"
                    f" '{run_date}' for run_id {run_id}."
                    f" Setting to None."
                )
                run_date = None
            run = SequencingRun(
                run_id=run_id,
                run_date=run_date,
                machine_id=machine_id,
                run_number=run_number,
                flowcell_id=flowcell_id,
                experiment_name=experiment_name,
                run_folder_uri=run_folder_uri,
                status=status,
                run_time=run_time if run_time else None
            )
            session.add(run)
    session.commit()


def scan(bucket: str, runs_folder_prefix: str, exclude_suffix: str | None = None):
    s3 = boto3.client("s3")

    print(f"Scanning s3://{bucket}/{runs_folder_prefix}")
    print("-" * 60)

    run_folders = get_run_folders(bucket, runs_folder_prefix)

    if not run_folders:
        print("No run folders found.")
        return

    print(f"Found {len(run_folders)} run folders:\n")

    run_ids = {}
    bad_run = 0
    with open("run_info.txt", "w") as run_info_file:
        # Write header
        print("\t".join(["run_id",
                         "run_date",
                         "machine_id",
                         "run_number",
                         "flowcell_id",
                         "experiment_name",
                         "run_folder_uri",
                         "status",
                         "run_time"]),
              file=run_info_file)

        for idx, folder in enumerate(sorted(run_folders)):
            print(f"\n[{idx + 1}/{len(run_folders)}] {folder}")
            folder_path = f"{runs_folder_prefix}{folder}"
            runinfo_path = find_run_info_xml(s3, bucket, folder_path)

            if runinfo_path:
                print(f"  RunInfo.xml: s3://{bucket}/{runinfo_path}")
                content = read_run_info_xml(s3, bucket, runinfo_path)
                run_info = extract_run_info_fields(content)
                run_id = run_info.get("run_id", "")
                run_date = run_id.split("_")[0]
                machine_id = run_info.get("machine_id", "")
                run_number = run_info.get("run_number", "")
                flowcell_id = run_info.get("flowcell_id", "")
                run_folder = f"s3://{bucket}/{runinfo_path.rsplit('/', 1)[0]}"

                samplesheet_info = read_samplesheet(run_folder)
                exp_name = samplesheet_info.get("experiment_name", "")
                status = "READY"
                run_time = ""

                if run_id in run_ids:
                    print(
                        f"  WARNING: Duplicate run_id {run_id}"
                        f" found in {run_ids[run_id]}"
                        f" and {run_folder}"
                    )
                    run_ids[run_id] = f"{run_ids[run_id]} | {run_folder}"
                else:
                    print("\t".join([run_id,
                                    run_date,
                                    machine_id,
                                    run_number,
                                    flowcell_id,
                                    exp_name,
                                    run_folder,
                                    status,
                                    run_time]),
                          file=run_info_file)
                    run_ids[run_id] = run_folder
            elif folder.count("_") == 4:
                # ONT runs: YYYYMMDD_HHMM_device_flowcell_hash
                run_id = folder.rstrip("/")
                if exclude_suffix and run_id.endswith(exclude_suffix):
                    print(f"  Skipping ONT run {run_id} due to exclude suffix {exclude_suffix}")
                    continue
                run_date, run_time, machine_id, flowcell_id, run_number = run_id.split("_")
                exp_name = ""
                status = "READY"
                run_folder = f"s3://{bucket}/{runs_folder_prefix}{folder.strip('/')}"
                print("\t".join([run_id,
                                 run_date,
                                 machine_id,
                                 run_number,
                                 flowcell_id,
                                 exp_name,
                                 run_folder,
                                 status,
                                 run_time]),
                      file=run_info_file)
            else:
                bad_run += 1

    print("\nSummary:")
    print(f"  Good runs: {len(run_ids)}")
    print(f"  Bad runs: {bad_run}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan S3 bucket for Illumina run folders"
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="S3 bucket name",
    )

    parser.add_argument(
        "--illumina",
        required=False,
        default="illumina/",
        help="S3 prefix to scan for Illumina runs",
    )

    parser.add_argument(
        "--ont",
        required=False,
        default="ONT/",
        help="S3 prefix to scan for ONT runs",
    )
    parser.add_argument(
        "--exclude-ont-suffix",
        default=None,
        help="Exclude ONT runs whose run_id ends with this suffix"
    )

    parser.add_argument(
        "--update-db",
        action="store_true",
        help="Update the database with the scanned runs (after scanning)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.illumina:
        scan(args.bucket, args.illumina)
    if args.ont:
        scan(args.bucket, args.ont, args.exclude_ont_suffix)
    if args.update_db:
        update_database()


if __name__ == "__main__":
    main()
