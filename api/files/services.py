"""
Services for the Files API
"""

from fastapi import HTTPException, status
from sqlmodel import Session
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from api.files.models import (
    FileBrowserData, FileBrowserFile, FileBrowserFolder, FileCreate, File,
    StorageBackend
)


def create_file(
    session: Session,
    file_create: FileCreate,
    file_content: bytes | None = None,
    storage_root: str = "storage",
) -> File:
    """Create a new file record and optionally store content"""

    # Generate unique file ID
    file_id = File.generate_file_id()

    # Use original_filename if provided, otherwise use filename
    original_filename = file_create.original_filename or file_create.filename

    # Generate file path
    file_path = File.generate_file_path(
        file_create.entity_type,
        file_create.entity_id,
        f"{file_id}_{file_create.filename}",
    )

    # Calculate file metadata if content is provided
    file_size = len(file_content) if file_content else None
    checksum = File.calculate_file_checksum(file_content) if file_content else None
    mime_type = File.get_mime_type(file_create.filename)

    # Create file record
    file_record = File(
        file_id=file_id,
        filename=file_create.filename,
        original_filename=original_filename,
        file_path=file_path,
        file_size=file_size,
        mime_type=mime_type,
        checksum=checksum,
        description=file_create.description,
        created_by=file_create.created_by,
        entity_type=file_create.entity_type,
        entity_id=file_create.entity_id,
        is_public=file_create.is_public,
        storage_backend=StorageBackend.S3,
    )

    # Store file content if provided
    if file_content:
        # 1. Save to standard database storage location
        full_path = Path(storage_root) / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_content)

        # 2. SPECIAL HANDLING: If samplesheet for run, also save to run folder
        if (
            file_create.file_type == FileType.SAMPLESHEET
            and file_create.entity_type == EntityType.RUN
        ):
            dual_storage_success = _save_samplesheet_to_run_folder(
                session, file_create.entity_id, file_content
            )
            # Add note to description about dual storage status
            if dual_storage_success:
                status_note = "[Dual-stored to run folder]"
            else:
                status_note = "[Database-only storage - run folder write failed]"

            if file_record.description:
                file_record.description = f"{file_record.description} {status_note}"
            else:
                file_record.description = status_note

    # Save to database
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    return file_record


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
