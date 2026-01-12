"""
Services for the Files API
"""
from datetime import datetime, timezone
import logging
from fastapi import HTTPException, status
from sqlmodel import Session, select
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from api.files.models import (
    FileBrowserData, FileBrowserFile, FileBrowserFolder, FileCreate, File,
    EntityType,
    StorageBackend
)


def _upload_to_s3(
    file_content: bytes, s3_uri: str, mime_type: str, s3_client=None
) -> bool:
    """
    Upload file content to S3.

    Args:
        file_content: File bytes to upload
        s3_uri: Full S3 URI (s3://bucket/key)
        mime_type: Content type for S3 metadata
        s3_client: Optional boto3 S3 client

    Returns:
        True if successful

    Raises:
        HTTPException: If upload fails
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="boto3 not available for S3 uploads. Install boto3 to enable S3 storage.",
        )

    try:
        bucket, key = _parse_s3_path(s3_uri)

        if s3_client is None:
            s3_client = boto3.client("s3")

        # NOTE: Depending on how the bucket is configured, you might need to
        # set ServerSideEncryption
        s3_client.put_object(
            Bucket=bucket,
            Key=key,
            Body=file_content,
            ContentType=mime_type,
            Metadata={
                "uploaded-by": "ngs360-api",
                "upload-timestamp": datetime.now(timezone.utc).isoformat()  # datetime.utcnow().isoformat(),
            },
            ServerSideEncryption="AES256",
        )

        logging.info(f"Successfully uploaded file to S3: {s3_uri}")
        return True

    except NoCredentialsError as exc:
        logging.error(f"AWS credentials not configured: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        message = exc.response["Error"]["Message"]

        if error_code == "NoSuchBucket":
            logging.error(f"S3 bucket not found in URI: {s3_uri}")
            logging.error(f"S3 ClientError ({error_code}): {message}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found in URI: {s3_uri}",
            ) from exc
        elif error_code == "AccessDenied":
            logging.error(f"Access denied to S3 bucket in URI: {s3_uri}")
            logging.error(f"S3 ClientError ({error_code}): {message}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 bucket: {s3_uri}",
            ) from exc
        else:
            logging.error(f"S3 ClientError ({error_code}): {message}")
            logging.error(f"S3 ClientError details: {exc.response['Error']}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except Exception as exc:
        logging.error(f"Failed to upload to S3: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error uploading to S3: {str(exc)}",
        ) from exc


def create_file(
    session: Session,
    s3_client,
    file_create: FileCreate,
    file_content: bytes | None = None,
) -> File:
    """
    Create a new file record and store content to appropriate backend.

    Args:
        session: Database session
        s3_client: boto3 S3 client for S3 operations
        file_create: FileCreate model with file metadata
        file_content: Optional file content bytes to store

    Returns:
        Created File object
    """
    # Use original_filename if provided, otherwise use filename
    original_filename = file_create.original_filename or file_create.filename

    # Validate and sanitize relative_path (security check)
    try:
        relative_path = File.validate_relative_path(file_create.relative_path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid relative_path: {str(e)}"
        )

    # Validate that the entity exists
    _validate_entity_exists(session, file_create.entity_type, file_create.entity_id)

    existing_file = _check_duplicate_file(
        session,
        file_create.entity_type,
        file_create.entity_id,
        file_create.filename,
        relative_path
    )
    
    if existing_file:
        if not file_create.overwrite:
            # File exists and overwrite not allowed - return error
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "File already exists",
                    "message": (
                        f"A file named '{file_create.filename}' already exists at this location. "
                        f"Use overwrite=true to replace it."
                    ),
                    "existing_file_id": existing_file.file_id,
                    "existing_file_path": existing_file.file_path,
                    "existing_upload_date": existing_file.upload_date.isoformat(),
                }
            )
        else:
            # Overwrite requested: archive the old file
            logging.info(
                f"Overwriting file: archiving {existing_file.file_id} "
                f"({file_create.filename}) and creating new version"
            )
            existing_file.is_archived = True
            existing_file.description = (
                f"{existing_file.description or ''} "
                f"[REPLACED on {datetime.now(timezone.utc).isoformat()} "
                f"by {file_create.created_by or 'unknown'}]"
            )
            session.add(existing_file)
            session.flush()  # Commit the archive before creating new file

    # Generate unique file ID
    file_id = File.generate_file_id()

    # Determine storage backend automatically from configuration
    from core.config import get_settings
    settings = get_settings()
    storage_backend = settings.STORAGE_BACKEND
    base_uri = settings.STORAGE_ROOT_PATH

    # Generate file path structure
    # Path: {entity_type}/{entity_id}/{relative_path}/{file_id}_{filename}
    relative_file_path = File.generate_file_path(
        file_create.entity_type,
        file_create.entity_id,
        f"{file_id}_{file_create.filename}",
        relative_path=relative_path,
    )

    # Full storage path (S3 URI or local path)
    storage_path = f"{base_uri.rstrip('/')}/{relative_file_path}"

    # Calculate file metadata if content is provided
    file_size = len(file_content) if file_content else None
    checksum = File.calculate_file_checksum(file_content) if file_content else None
    mime_type = File.get_mime_type(file_create.filename)

    # Create file record
    file_record = File(
        file_id=file_id,
        filename=file_create.filename,
        original_filename=original_filename,
        file_path=storage_path,
        file_size=file_size,
        mime_type=mime_type,
        checksum=checksum,
        description=file_create.description,
        created_by=file_create.created_by,
        entity_type=file_create.entity_type,
        entity_id=file_create.entity_id,
        is_public=file_create.is_public,
        storage_backend=storage_backend,
        relative_path=relative_path,
    )

    # Store file content based on backend
    if file_content:
        if storage_backend == StorageBackend.S3:
            # Upload to S3
            _upload_to_s3(file_content, storage_path, mime_type, s3_client)
            logging.info(
                f"File {file_id} uploaded to S3: {storage_path}"
            )
        else:
            # Write to local filesystem
            full_path = Path(storage_path)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "wb") as f:
                f.write(file_content)
            logging.info(
                f"File {file_id} saved to local storage: {full_path}"
            )

    # Save to database
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    return file_record


def _check_duplicate_file(
    session: Session,
    entity_type: EntityType,
    entity_id: str,
    filename: str,
    relative_path: str | None,
) -> File | None:
    """
    Check if a file with the same name already exists at the same location.

    Args:
        session: Database session
        entity_type: Type of entity (project or run)
        entity_id: ID of the entity
        filename: Name of the file to check
        relative_path: Subdirectory path (or None for root)

    Returns:
        Existing File object if found, None otherwise

    Note:
        Only considers non-archived files as potential duplicates.
        Archived files represent historical versions.
    """
    # Build query to find exact match
    query = select(File).where(
        File.entity_type == entity_type,
        File.entity_id == entity_id,
        File.filename == filename,
        File.is_archived == False,  # Only active files count as duplicates
    )

    # Handle NULL vs empty string for relative_path
    if relative_path is None or relative_path == "":
        query = query.where(
            (File.relative_path == None) | (File.relative_path == "")
        )
    else:
        query = query.where(File.relative_path == relative_path)

    existing_file = session.exec(query).first()

    return existing_file


def _validate_entity_exists(
    session: Session,
    entity_type: EntityType,
    entity_id: str
) -> None:
    """
    Validate that the parent entity (Project or Run) exists.

    Args:
        session: Database session
        entity_type: Type of entity
        entity_id: ID of entity

    Raises:
        HTTPException: If entity not found
    """
    if entity_type == EntityType.PROJECT:
        from api.project.models import Project
        project = session.exec(
            select(Project).where(Project.project_id == entity_id)
        ).first()

        if not project:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project not found: {entity_id}"
            )

    elif entity_type == EntityType.RUN:
        from api.runs.models import SequencingRun
        from api.runs.services import get_run

        run = get_run(session, entity_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run not found: {entity_id}"
            )


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse S3 path into bucket and prefix"""
    if not s3_path.startswith("s3://"):
        raise ValueError("Invalid S3 path format. Must start with s3://")

    # Remove s3:// prefix
    path_without_scheme = s3_path[5:]

    # Check for empty path after s3://
    if not path_without_scheme:
        raise ValueError("Invalid S3 path format. Bucket name is required")

    # Check for leading slash (s3:///)
    if path_without_scheme.startswith("/"):
        raise ValueError("Invalid S3 path format. Bucket name cannot start with /")

    # Check for double slashes anywhere in the path
    if "//" in path_without_scheme:
        raise ValueError("Invalid S3 path format. Path cannot contain double slashes")

    # Split into bucket and key
    if "/" in path_without_scheme:
        bucket, key = path_without_scheme.split("/", 1)
    else:
        bucket = path_without_scheme
        key = ""

    return bucket, key


def _list_s3(s3_path: str, s3_client=None) -> FileBrowserData:
    """
    Browse S3 bucket/prefix and return structured data.

    Args:
        s3_path: The S3 path to list
        s3_client: Optional boto3 S3 client
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3 to enable S3 browsing.",
        )

    try:
        # Parse both the request path and storage root
        bucket, prefix = _parse_s3_path(s3_path)

        # Initialize S3 client (use provided or create new)
        if s3_client is None:
            s3_client = boto3.client("s3")

        # List objects with the given prefix
        paginator = s3_client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(
            Bucket=bucket, Prefix=prefix, Delimiter="/"  # This helps us get "folders"
        )

        folders = []
        files = []

        for page in page_iterator:
            # Handle "folders" (common prefixes)
            for common_prefix in page.get("CommonPrefixes", []):
                folder_prefix = common_prefix["Prefix"]
                # Remove the current prefix to get just the folder name
                folder_name = folder_prefix[len(prefix):].rstrip("/")
                if folder_name:  # Skip empty names
                    folders.append(
                        FileBrowserFolder(
                            name=folder_name,
                            date="",  # S3 prefixes don't have modification dates
                        )
                    )

            # Handle actual files
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Skip if this is just the prefix itself (directory marker)
                if key == prefix:
                    continue

                # Remove the current prefix to get just the file name
                file_name = key[len(prefix):]

                # Skip files that are in subdirectories (contain '/')
                if "/" in file_name:
                    continue

                if file_name:  # Skip empty names
                    # Format the date
                    mod_time = obj["LastModified"]
                    date_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")

                    files.append(
                        FileBrowserFile(name=file_name, date=date_str, size=obj["Size"])
                    )

        # Sort folders and files by name
        folders.sort(key=lambda x: x.name.lower())
        files.sort(key=lambda x: x.name.lower())

        return FileBrowserData(folders=folders, files=files)

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
        ) from exc
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found: {bucket}",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 bucket: {bucket}",
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {exc.response['Error']['Message']}",
            ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error browsing S3: {str(exc)}",
        ) from exc


def download_file(s3_path: str, s3_client=None) -> tuple[bytes, str, str]:
    """
    Download a file from S3.

    Args:
        s3_path: The S3 URI of the file to download (e.g., s3://bucket/path/file.txt)
        s3_client: Optional boto3 S3 client

    Returns:
        Tuple of (file_content, content_type, filename)

    Raises:
        HTTPException: If file doesn't exist, access denied, or other errors
    """
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3 to enable S3 downloads.",
        )

    try:
        # Parse S3 path
        bucket, key = _parse_s3_path(s3_path)

        if not key:
            raise ValueError("S3 path must include a file key, not just a bucket")

        # Initialize S3 client if not provided
        if s3_client is None:
            s3_client = boto3.client("s3")

        # Get the object from S3
        response = s3_client.get_object(Bucket=bucket, Key=key)

        # Read the file content
        file_content = response['Body'].read()

        # Get content type from S3 metadata, default to binary
        content_type = response.get('ContentType', 'application/octet-stream')

        # Extract filename from the key (last part of the path)
        filename = key.split('/')[-1]

        return file_content, content_type, filename

    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
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
                detail=f"S3 bucket not found: {bucket}",
            ) from exc
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 object: {s3_path}",
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


def list_files(uri: str, s3_client=None) -> FileBrowserData:
    """
    List files and folders at the specified URI.

    Args:
        uri: The URI to list files from. Can be an S3 URI (s3://).
        s3_client: Optional boto3 S3 client for S3 operations.

    Returns:
        FileBrowserData containing the list of files and folders.

    Security:
        - For S3: No navigation outside uri is allowed
    """
    if not uri.startswith("s3://"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Storage root must be an S3 URI (s3://) for S3 paths",
        )

    try:
        return _list_s3(uri, s3_client=s3_client)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
