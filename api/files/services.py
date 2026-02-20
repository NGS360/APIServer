"""
Services for the unified Files API.

This module provides functions for:
- Creating files with entity associations, hashes, tags, and samples
- Looking up files by UUID or URI (with version support)
- Managing file uploads to S3 or local storage
- Browsing S3 file systems
"""

from datetime import datetime, timezone
import logging
import uuid as uuid_module
from pathlib import Path
from typing import List

from fastapi import HTTPException, status
from sqlmodel import Session, select, col

from api.files.models import (
    File,
    FileEntity,
    FileHash,
    FileTag,
    FileSample,
    FileCreate,
    FileUploadCreate,
    FileBrowserData,
    FileBrowserFile,
    FileBrowserFolder,
    FileEntityType,
)

try:
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

# ============================================================================
# File Creation Functions
# ============================================================================


def create_file(
    session: Session,
    file_create: FileCreate,
) -> File:
    """
    Create a new file record with all associations.

    This is the main function for creating files from external references
    (e.g., from pipeline outputs, manifests, etc.)

    Note: Same URI can exist multiple times with different created_on timestamps.
    This enables versioning - each call creates a new version.

    Args:
        session: Database session
        file_create: FileCreate model with file metadata

    Returns:
        Created File object with all relationships loaded
    """
    # Create the main file record
    file_record = File(
        uri=file_create.uri,
        original_filename=file_create.original_filename,
        size=file_create.size,
        created_by=file_create.created_by,
        source=file_create.source,
        storage_backend=file_create.storage_backend,
    )

    session.add(file_record)
    session.flush()  # Get the file ID

    # Create entity associations
    if file_create.entities:
        for entity_input in file_create.entities:
            entity = FileEntity(
                file_id=file_record.id,
                entity_type=entity_input.entity_type.upper(),
                entity_id=entity_input.entity_id,
                role=entity_input.role,
            )
            session.add(entity)

    # Create hash records
    if file_create.hashes:
        for algorithm, value in file_create.hashes.items():
            hash_record = FileHash(
                file_id=file_record.id,
                algorithm=algorithm,
                value=value,
            )
            session.add(hash_record)

    # Create tag records
    if file_create.tags:
        for key, value in file_create.tags.items():
            tag_record = FileTag(
                file_id=file_record.id,
                key=key,
                value=value,
            )
            session.add(tag_record)

    # Create sample associations
    if file_create.samples:
        for sample_input in file_create.samples:
            sample_record = FileSample(
                file_id=file_record.id,
                sample_name=sample_input.sample_name,
                role=sample_input.role,
            )
            session.add(sample_record)

    session.commit()
    session.refresh(file_record)

    return file_record


def create_file_upload(
    session: Session,
    s3_client,
    file_upload: FileUploadCreate,
    file_content: bytes | None = None,
) -> File:
    """
    Create a file record via upload with optional content storage.

    This is used for direct file uploads (e.g., sample sheets).

    Args:
        session: Database session
        s3_client: boto3 S3 client for S3 operations
        file_upload: FileUploadCreate model with upload metadata
        file_content: Optional file content bytes to store

    Returns:
        Created File object
    """
    # Validate and sanitize relative_path
    try:
        relative_path = File.validate_relative_path(file_upload.relative_path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid relative_path: {str(e)}"
        )

    # Validate entity exists
    _validate_entity_exists(
        session,
        file_upload.entity_type,
        file_upload.entity_id
    )

    # Get storage configuration
    from core.config import get_settings
    settings = get_settings()
    storage_backend = settings.STORAGE_BACKEND
    base_uri = settings.STORAGE_ROOT_PATH

    # Generate URI
    uri = File.generate_uri(
        base_uri,
        file_upload.entity_type,
        file_upload.entity_id,
        file_upload.filename,
        relative_path=relative_path,
    )

    # Check for existing file - if overwrite is false and a file exists at URI
    if not file_upload.overwrite:
        latest = get_latest_file_by_uri(session, uri)
        if latest:
            # Check if it's archived
            is_archived = any(
                t.key == "archived" and t.value == "true"
                for t in latest.tags
            )
            if not is_archived:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "File already exists",
                        "message": (
                            f"A file already exists at '{uri}'. "
                            f"Use overwrite=true to create a new version."
                        ),
                        "existing_file_id": str(latest.id),
                    }
                )

    # Calculate file metadata if content is provided
    file_size = len(file_content) if file_content else None
    checksum = File.calculate_checksum(file_content) if file_content else None
    mime_type = File.get_mime_type(file_upload.filename)

    # Create file record (new version)
    file_record = File(
        uri=uri,
        original_filename=file_upload.original_filename or file_upload.filename,
        size=file_size,
        created_by=file_upload.created_by,
        storage_backend=storage_backend,
    )

    session.add(file_record)
    session.flush()

    # Create entity association
    entity = FileEntity(
        file_id=file_record.id,
        entity_type=file_upload.entity_type.upper(),
        entity_id=file_upload.entity_id,
        role=file_upload.role,
    )
    session.add(entity)

    # Add hash if content was provided
    if checksum:
        hash_record = FileHash(
            file_id=file_record.id,
            algorithm="sha256",
            value=checksum,
        )
        session.add(hash_record)

    # Add description tag if provided
    if file_upload.description:
        tag = FileTag(
            file_id=file_record.id,
            key="description",
            value=file_upload.description,
        )
        session.add(tag)

    # Add public tag if set
    if file_upload.is_public:
        tag = FileTag(
            file_id=file_record.id,
            key="public",
            value="true",
        )
        session.add(tag)

    # Store file content to backend
    if file_content:
        allow_overwrite = file_upload.overwrite
        if storage_backend.upper() == "S3":
            _upload_to_s3(
                file_content, uri, mime_type, s3_client,
                allow_overwrite=allow_overwrite
            )
            logging.info("File uploaded to S3: %s", uri)
        else:
            _write_local_file(uri, file_content, allow_overwrite=allow_overwrite)
            logging.info("File saved to local storage: %s", uri)

    session.commit()
    session.refresh(file_record)

    return file_record


# ============================================================================
# File Retrieval Functions
# ============================================================================


def get_file_by_id(session: Session, file_id: uuid_module.UUID) -> File:
    """
    Retrieve file by UUID.

    Args:
        session: Database session
        file_id: UUID of the file

    Returns:
        File object with relationships loaded

    Raises:
        HTTPException: If file not found
    """
    file_record = session.get(File, file_id)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {file_id}"
        )
    return file_record


def get_latest_file_by_uri(session: Session, uri: str) -> File | None:
    """
    Retrieve the latest version of a file by URI.

    Args:
        session: Database session
        uri: URI of the file

    Returns:
        File object or None if not found
    """
    return session.exec(
        select(File)
        .where(File.uri == uri)
        .order_by(col(File.created_on).desc())
    ).first()


def get_file_by_uri(session: Session, uri: str) -> File:
    """
    Retrieve the latest version of a file by URI.

    Args:
        session: Database session
        uri: URI of the file

    Returns:
        File object with relationships loaded

    Raises:
        HTTPException: If file not found
    """
    file_record = get_latest_file_by_uri(session, uri)
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {uri}"
        )
    return file_record


def get_file_versions(session: Session, uri: str) -> List[File]:
    """
    Retrieve all versions of a file by URI, ordered by created_on descending.

    Args:
        session: Database session
        uri: URI of the file

    Returns:
        List of File objects (newest first)
    """
    return list(session.exec(
        select(File)
        .where(File.uri == uri)
        .order_by(col(File.created_on).desc())
    ).all())


def list_files_by_entity(
    session: Session,
    entity_type: str,
    entity_id: str,
    include_archived: bool = False,
    latest_only: bool = True,
) -> List[File]:
    """
    List all files associated with an entity.

    Args:
        session: Database session
        entity_type: Type of entity (PROJECT, RUN, SAMPLE, QCRECORD)
        entity_id: ID of the entity
        include_archived: Whether to include archived files
        latest_only: If True, return only the latest version of each URI

    Returns:
        List of File objects
    """
    query = (
        select(File)
        .join(FileEntity)
        .where(
            FileEntity.entity_type == entity_type.upper(),
            FileEntity.entity_id == entity_id
        )
    )

    if not include_archived:
        # Subquery to find files with archived=true tag
        archived_subquery = (
            select(FileTag.file_id)
            .where(
                FileTag.key == "archived",
                FileTag.value == "true"
            )
        )
        query = query.where(File.id.notin_(archived_subquery))

    files = list(session.exec(query).all())

    if latest_only:
        # Group by URI and keep only the latest
        uri_to_latest = {}
        for f in files:
            if f.uri not in uri_to_latest:
                uri_to_latest[f.uri] = f
            elif f.created_on > uri_to_latest[f.uri].created_on:
                uri_to_latest[f.uri] = f
        return list(uri_to_latest.values())

    return files


# ============================================================================
# Entity Validation
# ============================================================================


def _validate_entity_exists(
    session: Session,
    entity_type: FileEntityType,
    entity_id: str
) -> None:
    """
    Validate that the parent entity exists.

    Args:
        session: Database session
        entity_type: Type of entity
        entity_id: ID of entity

    Raises:
        HTTPException: If entity not found
    """
    if entity_type == FileEntityType.PROJECT:
        from api.project.models import Project
        project = session.exec(
            select(Project).where(Project.project_id == entity_id)
        ).first()
        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project not found: {entity_id}"
            )

    elif entity_type == FileEntityType.RUN:
        from api.runs.services import get_run
        run = get_run(session, entity_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run not found: {entity_id}"
            )

    elif entity_type == FileEntityType.SAMPLE:
        from api.samples.models import Sample
        sample = session.exec(
            select(Sample).where(Sample.id == entity_id)
        ).first()
        if not sample:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sample not found: {entity_id}"
            )

    elif entity_type == FileEntityType.QCRECORD:
        from api.qcmetrics.models import QCRecord
        qcrecord = session.exec(
            select(QCRecord).where(QCRecord.id == entity_id)
        ).first()
        if not qcrecord:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"QCRecord not found: {entity_id}"
            )


# ============================================================================
# S3 Operations
# ============================================================================


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse S3 path into bucket and key."""
    if not s3_path.startswith("s3://"):
        raise ValueError("Invalid S3 path format. Must start with s3://")

    path_without_scheme = s3_path[5:]

    if not path_without_scheme:
        raise ValueError("Invalid S3 path format. Bucket name is required")

    if path_without_scheme.startswith("/"):
        raise ValueError(
            "Invalid S3 path format. Bucket name cannot start with /"
        )

    if "//" in path_without_scheme:
        raise ValueError(
            "Invalid S3 path format. Path cannot contain double slashes"
        )

    if "/" in path_without_scheme:
        bucket, key = path_without_scheme.split("/", 1)
    else:
        bucket = path_without_scheme
        key = ""

    return bucket, key


def _upload_to_s3(
    file_content: bytes,
    s3_uri: str,
    mime_type: str,
    s3_client=None,
    allow_overwrite: bool = False
) -> bool:
    """
    Upload file content to S3.

    Args:
        file_content: File bytes to upload
        s3_uri: Full S3 URI (s3://bucket/key)
        mime_type: Content type for S3 metadata
        s3_client: Optional boto3 S3 client
        allow_overwrite: If False (default), check if object exists and raise error

    Returns:
        True if successful

    Raises:
        HTTPException: If upload fails or object exists when allow_overwrite=False
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="boto3 not available. Install boto3 to enable S3 storage.",
        )

    try:
        bucket, key = _parse_s3_path(s3_uri)

        if s3_client is None:
            s3_client = boto3.client("s3")

        # Check if object exists when overwrite is not allowed
        if not allow_overwrite:
            try:
                s3_client.head_object(Bucket=bucket, Key=key)
                # Object exists - raise conflict
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "File already exists in S3",
                        "message": (
                            f"Object already exists at '{s3_uri}'. "
                            "Use overwrite=true to replace."
                        ),
                        "uri": s3_uri,
                    }
                )
            except ClientError as e:
                # 404 means object doesn't exist - that's what we want
                if e.response["Error"]["Code"] != "404":
                    raise

        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_content,
            ContentType=mime_type,
            Metadata={
                "uploaded-by": "ngs360-api",
                "upload-timestamp": datetime.now(timezone.utc).isoformat()
            },
            ServerSideEncryption="AES256",
        )

        logging.info("Successfully uploaded file to S3: %s", s3_uri)
        return True

    except NoCredentialsError as exc:
        logging.error("AWS credentials not configured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        message = exc.response["Error"]["Message"]

        if error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found: {s3_uri}",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 bucket: {s3_uri}",
            ) from exc
        else:
            logging.error("S3 ClientError (%s): %s", error_code, message)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {message}",
            ) from exc
    except Exception as exc:
        logging.error("Failed to upload to S3: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error uploading to S3: {str(exc)}",
        ) from exc


def _write_local_file(
    uri: str,
    file_content: bytes,
    allow_overwrite: bool = False
) -> None:
    """
    Write file content to local filesystem.

    Args:
        uri: File path (should be a valid local filesystem path)
        file_content: Bytes to write
        allow_overwrite: If False (default), raises error if file exists

    Raises:
        HTTPException: If path is invalid or file exists when allow_overwrite=False
    """
    full_path = Path(uri)

    # Security: Validate path doesn't escape allowed directories
    # Reject paths that look like URI schemes (e.g., s3://, file://)
    if "://" in uri or uri.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Invalid local file path",
                "message": (
                    "Local file paths must be relative. "
                    f"Got: '{uri}'"
                ),
            }
        )

    # Resolve and check for path traversal
    try:
        resolved = full_path.resolve()
        cwd = Path.cwd().resolve()
        # Ensure resolved path is under current working directory
        resolved.relative_to(cwd)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Path traversal detected",
                "message": "File path must be within the storage directory.",
            }
        )

    # Check if file already exists
    if not allow_overwrite and full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "File already exists",
                "message": (
                    f"File already exists at '{uri}'. "
                    "Use overwrite=true to replace."
                ),
                "uri": uri,
            }
        )

    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "wb") as f:
        f.write(file_content)


def download_file(s3_path: str, s3_client=None) -> tuple[bytes, str, str]:
    """
    Download a file from S3.

    Args:
        s3_path: The S3 URI of the file to download
        s3_client: Optional boto3 S3 client

    Returns:
        Tuple of (file_content, content_type, filename)

    Raises:
        HTTPException: If file doesn't exist, access denied, or other errors
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3.",
        )

    try:
        bucket, key = _parse_s3_path(s3_path)

        if not key:
            raise ValueError(
                "S3 path must include a file key, not just a bucket"
            )

        if s3_client is None:
            s3_client = boto3.client("s3")

        response = s3_client.get_object(Bucket=bucket, Key=key)
        file_content = response['Body'].read()
        content_type = response.get('ContentType', 'application/octet-stream')
        filename = key.split('/')[-1]

        return file_content, content_type, filename

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchKey":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {s3_path}",
            ) from exc
        elif error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="S3 bucket not found",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: {s3_path}",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error downloading from S3: {str(exc)}",
        ) from exc


def list_s3_files(uri: str, s3_client=None) -> FileBrowserData:
    """
    List files and folders at the specified S3 URI.

    Args:
        uri: The S3 URI to list files from
        s3_client: Optional boto3 S3 client

    Returns:
        FileBrowserData containing files and folders
    """
    if not uri.startswith("s3://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URI must be an S3 URI (s3://)",
        )

    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3.",
        )

    try:
        bucket, prefix = _parse_s3_path(uri)

        if s3_client is None:
            s3_client = boto3.client("s3")

        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(
            Bucket=bucket, Prefix=prefix, Delimiter="/"
        )

        folders = []
        files = []

        for page in page_iterator:
            for common_prefix in page.get("CommonPrefixes", []):
                folder_prefix = common_prefix["Prefix"]
                folder_name = folder_prefix[len(prefix):].rstrip("/")
                if folder_name:
                    folders.append(
                        FileBrowserFolder(name=folder_name, date="")
                    )

            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key == prefix:
                    continue
                file_name = key[len(prefix):]
                if "/" in file_name:
                    continue
                if file_name:
                    mod_time = obj["LastModified"]
                    date_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")
                    files.append(
                        FileBrowserFile(
                            name=file_name,
                            date=date_str,
                            size=obj["Size"]
                        )
                    )

        folders.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())

        return FileBrowserData(folders=folders, files=files)

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="S3 bucket not found",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to S3 bucket",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error browsing S3: {str(exc)}",
        ) from exc
