#!/usr/bin/env python
"""
Bulk registration script for existing S3 files.

This script scans S3 buckets and registers existing files in the database
without moving them. Files remain in S3 but become discoverable through the API.

Usage:
    PYTHONPATH=.
    python scripts/register_s3_files.py --bucket my-bucket --prefix data/
    python scripts/register_s3_files.py --config s3_config.json
    python scripts/register_s3_files.py --bucket my-bucket --dry-run
"""

import argparse
import json
import mimetypes
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from sqlmodel import Session, select

# Add project root to path for imports
# sys.path.append(str(Path(__file__).parent.parent))

from api.files.models import FileCreate, FileType, EntityType, StorageBackend
from api.files.services import create_file
from core.db import get_session
from core.logger import logger


class S3FileRegistrar:
    """Handles bulk registration of S3 files to the database."""

    def __init__(self, session: Session, dry_run: bool = False):
        self.session = session
        self.dry_run = dry_run
        self.stats = {"scanned": 0, "registered": 0, "skipped": 0, "errors": 0}

        # File type mapping based on extensions
        self.file_type_mapping = {
            ".fastq": FileType.FASTQ,
            ".fastq.gz": FileType.FASTQ,
            ".fq": FileType.FASTQ,
            ".fq.gz": FileType.FASTQ,
            ".bam": FileType.BAM,
            ".sam": FileType.BAM,
            ".vcf": FileType.VCF,
            ".vcf.gz": FileType.VCF,
            ".csv": FileType.SAMPLESHEET,
            ".xlsx": FileType.SAMPLESHEET,
            ".json": FileType.METRICS,
            ".html": FileType.REPORT,
            ".pdf": FileType.REPORT,
            ".log": FileType.LOG,
            ".txt": FileType.LOG,
            ".png": FileType.IMAGE,
            ".jpg": FileType.IMAGE,
            ".jpeg": FileType.IMAGE,
            ".svg": FileType.IMAGE,
            ".doc": FileType.DOCUMENT,
            ".docx": FileType.DOCUMENT,
            ".md": FileType.DOCUMENT,
        }

    def get_file_type(self, filename: str) -> FileType:
        """Determine file type based on filename extension."""
        filename_lower = filename.lower()

        # Check for compound extensions first (e.g., .fastq.gz)
        for ext, file_type in self.file_type_mapping.items():
            if filename_lower.endswith(ext):
                return file_type

        return FileType.OTHER

    def extract_entity_info(
        self, s3_key: str, patterns: Dict[str, str]
    ) -> Tuple[EntityType, str]:
        """
        Extract entity type and ID from S3 key using regex patterns.

        Args:
            s3_key: S3 object key
            patterns: Dict of entity_type -> regex pattern

        Returns:
            Tuple of (EntityType, entity_id)
        """
        for entity_type_str, pattern in patterns.items():
            match = re.search(pattern, s3_key)
            if match:
                entity_id = match.group(1)
                entity_type = (
                    EntityType.PROJECT
                    if entity_type_str == "project"
                    else EntityType.RUN
                )
                return entity_type, entity_id

        # Default fallback - extract from path structure
        path_parts = s3_key.split("/")
        if len(path_parts) >= 2:
            # Assume format like: projects/PROJ001/... or runs/RUN001/...
            if path_parts[0].lower() in ["projects", "project"]:
                return EntityType.PROJECT, path_parts[1]
            elif path_parts[0].lower() in ["runs", "run", "sequencing_runs"]:
                return EntityType.RUN, path_parts[1]

        # Final fallback - use first directory as project
        return EntityType.PROJECT, path_parts[0] if path_parts else "unknown"

    def file_already_registered(self, s3_uri: str) -> bool:
        """Check if file is already registered in database."""
        from api.files.models import File

        existing = self.session.exec(
            select(File).where(File.file_path == s3_uri)
        ).first()

        return existing is not None

    def register_s3_object(
        self, bucket: str, obj: dict, entity_patterns: Dict[str, str]
    ) -> bool:
        """
        Register a single S3 object in the database.

        Args:
            bucket: S3 bucket name
            obj: S3 object metadata from boto3
            entity_patterns: Regex patterns for extracting entity info

        Returns:
            True if registered successfully, False otherwise
        """
        s3_key = obj["Key"]
        filename = Path(s3_key).name
        s3_uri = f"s3://{bucket}/{s3_key}"

        # Skip directories
        if s3_key.endswith("/"):
            return False

        # Skip if already registered
        if self.file_already_registered(s3_uri):
            logger.debug(f"File already registered: {s3_uri}")
            self.stats["skipped"] += 1
            return False

        # Extract entity information
        entity_type, entity_id = self.extract_entity_info(s3_key, entity_patterns)

        # Determine file type
        file_type = self.get_file_type(filename)

        # Get MIME type
        mime_type, _ = mimetypes.guess_type(filename)

        # Create file record
        file_create = FileCreate(
            filename=filename,
            original_filename=filename,
            description=f"Imported from S3: {s3_key}",
            file_type=file_type,
            entity_type=entity_type,
            entity_id=entity_id,
            is_public=False,  # Default to private
            created_by="s3_bulk_import",
        )

        if self.dry_run:
            logger.info(
                f"[DRY RUN] Would register: {s3_uri} -> {entity_type.value}/{entity_id}"
            )
            self.stats["registered"] += 1
            return True

        try:
            # Register file in database with S3 storage path
            file_record = create_file(
                session=self.session,
                file_create=file_create,
                file_content=None,  # No content upload, file stays in S3
                storage_path=s3_uri,  # Use S3 URI as storage path
            )

            # Update the file record with S3-specific information
            file_record.file_size = obj.get("Size", 0)
            file_record.mime_type = mime_type
            file_record.upload_date = obj.get(
                "LastModified", datetime.now(timezone.utc)
            )

            self.session.add(file_record)
            self.session.commit()

            logger.info(f"Registered: {s3_uri} -> {file_record.file_id}")
            self.stats["registered"] += 1
            return True

        except Exception as e:
            logger.error(f"Failed to register {s3_uri}: {e}")
            self.stats["errors"] += 1
            self.session.rollback()
            return False

    def scan_bucket(
        self, bucket: str, prefix: str = "", entity_patterns: Dict[str, str] = None
    ) -> None:
        """
        Scan S3 bucket and register files.

        Args:
            bucket: S3 bucket name
            prefix: S3 key prefix to filter objects
            entity_patterns: Regex patterns for extracting entity info
        """
        if entity_patterns is None:
            entity_patterns = {
                "project": r"(?:projects?|proj)/([^/]+)",
                "run": r"(?:runs?|sequencing_runs?)/([^/]+)",
            }

        try:
            s3_client = boto3.client("s3")

            # Test bucket access
            try:
                s3_client.head_bucket(Bucket=bucket)
            except ClientError as e:
                error_code = e.response["Error"]["Code"]
                if error_code == "404":
                    logger.error(f"Bucket '{bucket}' does not exist")
                elif error_code == "403":
                    logger.error(f"Access denied to bucket '{bucket}'")
                else:
                    logger.error(f"Error accessing bucket '{bucket}': {e}")
                return

            logger.info(f"Scanning S3 bucket: s3://{bucket}/{prefix}")

            # List objects with pagination
            paginator = s3_client.get_paginator("list_objects_v2")
            page_iterator = paginator.paginate(Bucket=bucket, Prefix=prefix)

            for page in page_iterator:
                if "Contents" not in page:
                    continue

                for obj in page["Contents"]:
                    self.stats["scanned"] += 1
                    self.register_s3_object(bucket, obj, entity_patterns)

                    # Progress logging
                    if self.stats["scanned"] % 100 == 0:
                        logger.info(
                            f"Progress: {self.stats['scanned']} scanned, "
                            f"{self.stats['registered']} registered, "
                            f"{self.stats['skipped']} skipped, "
                            f"{self.stats['errors']} errors"
                        )

        except NoCredentialsError:
            logger.error("AWS credentials not found. Please configure AWS credentials.")
        except Exception as e:
            logger.error(f"Error scanning bucket: {e}")

    def print_summary(self):
        """Print registration summary."""
        logger.info("=" * 50)
        logger.info("REGISTRATION SUMMARY")
        logger.info("=" * 50)
        logger.info(f"Files scanned:    {self.stats['scanned']}")
        logger.info(f"Files registered: {self.stats['registered']}")
        logger.info(f"Files skipped:    {self.stats['skipped']}")
        logger.info(f"Errors:           {self.stats['errors']}")

        if self.dry_run:
            logger.info("\n*** DRY RUN MODE - No files were actually registered ***")


def load_config(config_file: str) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(config_file, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in configuration file: {e}")
        sys.exit(1)


def create_sample_config():
    """Create a sample configuration file."""
    config = {
        "buckets": [
            {
                "name": "my-ngs-data-bucket",
                "prefix": "projects/",
                "entity_patterns": {
                    "project": r"projects/([^/]+)",
                    "run": r"runs/([^/]+)",
                },
            },
            {
                "name": "my-runs-bucket",
                "prefix": "sequencing_runs/",
                "entity_patterns": {"run": r"sequencing_runs/([^/]+)"},
            },
        ],
        "dry_run": True,
    }

    with open("s3_registration_config.json", "w") as f:
        json.dump(config, f, indent=2)

    logger.info("Sample configuration created: s3_registration_config.json")
    logger.info("Edit this file with your S3 bucket details and run:")
    logger.info(
        "python scripts/register_s3_files.py --config s3_registration_config.json"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Bulk register existing S3 files in the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Register all files from a bucket
  python scripts/register_s3_files.py --bucket my-bucket

  # Register files with specific prefix
  python scripts/register_s3_files.py --bucket my-bucket --prefix projects/

  # Dry run to see what would be registered
  python scripts/register_s3_files.py --bucket my-bucket --dry-run

  # Use configuration file for multiple buckets
  python scripts/register_s3_files.py --config s3_config.json

  # Create sample configuration file
  python scripts/register_s3_files.py --create-config
        """,
    )

    parser.add_argument("--bucket", help="S3 bucket name")
    parser.add_argument("--prefix", default="", help="S3 key prefix to filter objects")
    parser.add_argument("--config", help="JSON configuration file for multiple buckets")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be registered without making changes",
    )
    parser.add_argument(
        "--create-config",
        action="store_true",
        help="Create a sample configuration file",
    )

    args = parser.parse_args()

    if args.create_config:
        create_sample_config()
        return

    if not args.bucket and not args.config:
        parser.error("Either --bucket or --config must be specified")

    # Get database session
    try:
        session = next(get_session())
    except Exception as e:
        logger.error(f"Failed to create database session: {e}")
        sys.exit(1)

    registrar = S3FileRegistrar(session, dry_run=args.dry_run)

    try:
        if args.config:
            # Load configuration and process multiple buckets
            config = load_config(args.config)
            dry_run = config.get("dry_run", args.dry_run)
            registrar.dry_run = dry_run

            for bucket_config in config["buckets"]:
                bucket = bucket_config["name"]
                prefix = bucket_config.get("prefix", "")
                entity_patterns = bucket_config.get("entity_patterns")

                logger.info(f"Processing bucket: {bucket}")
                registrar.scan_bucket(bucket, prefix, entity_patterns)

        else:
            # Single bucket mode
            registrar.scan_bucket(args.bucket, args.prefix)

    finally:
        registrar.print_summary()
        session.close()


if __name__ == "__main__":
    main()
