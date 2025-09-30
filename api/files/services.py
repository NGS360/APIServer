"""
Services for managing files.
"""

import hashlib
import secrets
import string
import os
import logging
from pathlib import Path
from datetime import datetime
from sqlmodel import select, Session, func
from pydantic import PositiveInt
from fastapi import HTTPException, status

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from api.files.models import (
    File,
    FileCreate,
    FileUpdate,
    FilePublic,
    FilesPublic,
    FileFilters,
    FileType,
    EntityType,
    StorageBackend,
    FileBrowserData,
    FileBrowserFolder,
    FileBrowserFile,
)


def generate_file_id() -> str:
    """Generate a unique file ID"""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


def generate_file_path(
    entity_type: EntityType, entity_id: str, file_type: FileType, filename: str
) -> str:
    """Generate a structured file path"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    month = now.strftime("%m")

    # Create path structure: /{entity_type}/{entity_id}/{file_type}/{year}/{month}/{filename}
    path_parts = [entity_type.value, entity_id, file_type.value, year, month, filename]
    return "/".join(path_parts)


def calculate_file_checksum(file_content: bytes) -> str:
    """Calculate SHA-256 checksum of file content"""
    return hashlib.sha256(file_content).hexdigest()


def get_mime_type(filename: str) -> str:
    """Get MIME type based on file extension"""
    import mimetypes

    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


def _is_valid_storage_path(path: str) -> bool:
    """Validate storage path format"""
    # Allow S3 paths, local paths, network paths
    valid_prefixes = ["s3://", "/", "file://", "smb://", "ftp://"]
    return any(path.startswith(prefix) for prefix in valid_prefixes)


def _save_samplesheet_to_run_folder(
    session: Session, run_barcode: str, file_content: bytes
) -> bool:
    """
    Save samplesheet content to the run's folder URI location.
    Returns True if successful, False otherwise.
    """
    from smart_open import open as smart_open

    try:
        # Import here to avoid circular imports
        from api.runs.services import get_run

        # Get run information
        run = get_run(session, run_barcode)
        if not run or not run.run_folder_uri:
            logging.warning(f"No run folder URI found for run {run_barcode}")
            return False

        # Construct samplesheet path - always use SampleSheet.csv as the standard name
        samplesheet_path = f"{run.run_folder_uri.rstrip('/')}/SampleSheet.csv"

        # Validate path format
        if not _is_valid_storage_path(samplesheet_path):
            logging.warning(f"Invalid storage path format: {samplesheet_path}")
            return False

        # Save using smart_open (handles S3, local, network paths)
        with smart_open(samplesheet_path, "wb") as f:
            f.write(file_content)

        logging.info(
            f"Successfully saved samplesheet to run folder: {samplesheet_path}"
        )
        return True

    except Exception as e:
        # Log error but don't fail the upload
        logging.error(f"Failed to save samplesheet to run folder {run_barcode}: {e}")
        return False


def create_file(
    session: Session,
    file_create: FileCreate,
    file_content: bytes | None = None,
    storage_root: str = "storage",
) -> File:
    """Create a new file record and optionally store content"""

    # Generate unique file ID
    file_id = generate_file_id()

    # Use original_filename if provided, otherwise use filename
    original_filename = file_create.original_filename or file_create.filename

    # Generate file path
    file_path = generate_file_path(
        file_create.entity_type,
        file_create.entity_id,
        file_create.file_type,
        f"{file_id}_{file_create.filename}",
    )

    # Calculate file metadata if content is provided
    file_size = len(file_content) if file_content else None
    checksum = calculate_file_checksum(file_content) if file_content else None
    mime_type = get_mime_type(file_create.filename)

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
        file_type=file_create.file_type,
        created_by=file_create.created_by,
        entity_type=file_create.entity_type,
        entity_id=file_create.entity_id,
        is_public=file_create.is_public,
        storage_backend=StorageBackend.LOCAL,
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


def get_file(session: Session, file_id: str) -> File:
    """Get a file by its file_id"""
    file_record = session.exec(select(File).where(File.file_id == file_id)).first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found",
        )

    return file_record


def get_file_by_id(session: Session, id: str) -> File:
    """Get a file by its internal UUID"""
    file_record = session.exec(select(File).where(File.id == id)).first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with internal id {id} not found",
        )

    return file_record


def update_file(session: Session, file_id: str, file_update: FileUpdate) -> File:
    """Update file metadata"""
    file_record = get_file(session, file_id)

    # Update fields that are provided
    update_data = file_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(file_record, field, value)

    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    return file_record


def delete_file(session: Session, file_id: str, storage_root: str = "storage") -> bool:
    """Delete a file record and its content"""
    file_record = get_file(session, file_id)

    # Delete physical file if it exists
    full_path = Path(storage_root) / file_record.file_path
    if full_path.exists():
        full_path.unlink()

        # Try to remove empty directories
        try:
            full_path.parent.rmdir()
        except OSError:
            # Directory not empty, that's fine
            pass

    # Delete from database
    session.delete(file_record)
    session.commit()

    return True


def list_files(
    session: Session,
    filters: FileFilters | None = None,
    page: PositiveInt = 1,
    per_page: PositiveInt = 20,
    sort_by: str = "upload_date",
    sort_order: str = "desc",
) -> FilesPublic:
    """List files with filtering and pagination"""

    # Build query
    query = select(File)

    # Apply filters
    if filters:
        if filters.entity_type:
            query = query.where(File.entity_type == filters.entity_type)
        if filters.entity_id:
            query = query.where(File.entity_id == filters.entity_id)
        if filters.file_type:
            query = query.where(File.file_type == filters.file_type)
        if filters.mime_type:
            query = query.where(File.mime_type == filters.mime_type)
        if filters.created_by:
            query = query.where(File.created_by == filters.created_by)
        if filters.is_public is not None:
            query = query.where(File.is_public == filters.is_public)
        if filters.is_archived is not None:
            query = query.where(File.is_archived == filters.is_archived)
        if filters.search_query:
            search_term = f"%{filters.search_query}%"
            query = query.where(
                (File.filename.ilike(search_term))
                | (File.description.ilike(search_term))
            )

    # Get total count
    total_count = session.exec(select(func.count()).select_from(query.subquery())).one()

    # Calculate pagination
    total_pages = (total_count + per_page - 1) // per_page

    # Apply sorting
    sort_field = getattr(File, sort_by, File.upload_date)
    if sort_order == "desc":
        query = query.order_by(sort_field.desc())
    else:
        query = query.order_by(sort_field.asc())

    # Apply pagination
    query = query.offset((page - 1) * per_page).limit(per_page)

    # Execute query
    files = session.exec(query).all()

    # Convert to public models
    public_files = [
        FilePublic(
            file_id=file.file_id,
            filename=file.filename,
            original_filename=file.original_filename,
            file_size=file.file_size,
            mime_type=file.mime_type,
            description=file.description,
            file_type=file.file_type,
            upload_date=file.upload_date,
            created_by=file.created_by,
            entity_type=file.entity_type,
            entity_id=file.entity_id,
            is_public=file.is_public,
            is_archived=file.is_archived,
            storage_backend=file.storage_backend,
            checksum=file.checksum,
        )
        for file in files
    ]

    return FilesPublic(
        data=public_files,
        total_items=total_count,
        total_pages=total_pages,
        current_page=page,
        per_page=per_page,
        has_next=page < total_pages,
        has_prev=page > 1,
    )


def get_file_content(
    session: Session, file_id: str, storage_root: str = "storage"
) -> bytes:
    """Get file content from storage"""
    file_record = get_file(session, file_id)

    full_path = Path(storage_root) / file_record.file_path
    if not full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File content not found at {file_record.file_path}",
        )

    with open(full_path, "rb") as f:
        return f.read()


def list_files_for_entity(
    session: Session,
    entity_type: EntityType,
    entity_id: str,
    page: PositiveInt = 1,
    per_page: PositiveInt = 20,
    file_type: FileType | None = None,
) -> FilesPublic:
    """List files for a specific entity (project or run)"""
    filters = FileFilters(
        entity_type=entity_type, entity_id=entity_id, file_type=file_type
    )

    return list_files(session=session, filters=filters, page=page, per_page=per_page)


def get_file_count_for_entity(
    session: Session, entity_type: EntityType, entity_id: str
) -> int:
    """Get the count of files for a specific entity"""
    count = session.exec(
        select(func.count(File.id)).where(
            File.entity_type == entity_type,
            File.entity_id == entity_id,
            ~File.is_archived,
        )
    ).one()

    return count


def update_file_content(
    session: Session, file_id: str, content: bytes, storage_root: str = "storage"
) -> File:
    """Update file content"""
    # Get the file record
    file_record = get_file(session, file_id)

    # Calculate new file metadata
    file_size = len(content)
    checksum = calculate_file_checksum(content)

    # Write content to storage
    storage_path = Path(storage_root) / file_record.file_path
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    storage_path.write_bytes(content)

    # Update file record
    file_record.file_size = file_size
    file_record.checksum = checksum

    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    return file_record


def browse_filesystem(
    directory_path: str, storage_root: str = "storage"
) -> FileBrowserData:
    """
    Browse filesystem directory and return structured data.

    Automatically detects if the path is S3 (s3://bucket/key) or local filesystem
    and routes to the appropriate handler.
    """
    # Check if this is an S3 path
    if _is_s3_path(directory_path):
        return browse_s3(directory_path)

    # Handle local filesystem
    return _browse_local_filesystem(directory_path, storage_root)


def _browse_local_filesystem(
    directory_path: str, storage_root: str = "storage"
) -> FileBrowserData:
    """Browse local filesystem directory and return structured data"""

    # Construct full path
    if os.path.isabs(directory_path):
        full_path = Path(directory_path)
    else:
        full_path = Path(storage_root) / directory_path

    # Check if directory exists and is accessible
    if not full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory not found: {directory_path}",
        )

    if not full_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {directory_path}",
        )

    folders = []
    files = []

    try:
        # List directory contents
        for item in full_path.iterdir():
            # Get modification time
            stat = item.stat()
            mod_time = datetime.fromtimestamp(stat.st_mtime)
            date_str = mod_time.strftime("%Y-%m-%d %H:%M:%S")

            if item.is_dir():
                folders.append(FileBrowserFolder(name=item.name, date=date_str))
            else:
                files.append(
                    FileBrowserFile(name=item.name, date=date_str, size=stat.st_size)
                )

    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied accessing directory: {directory_path}",
        )

    # Sort folders and files by name
    folders.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())

    return FileBrowserData(folders=folders, files=files)


def _is_s3_path(path: str) -> bool:
    """Check if a path is an S3 URI (s3://bucket/key)"""
    return path.startswith("s3://")


def _parse_s3_path(s3_path: str) -> tuple[str, str]:
    """Parse S3 path into bucket and prefix"""
    if not s3_path.startswith("s3://"):
        raise ValueError("Invalid S3 path format. Must start with s3://")

    # Remove s3:// prefix
    path_without_scheme = s3_path[5:]

    # Check for empty path after s3://
    if not path_without_scheme:
        raise ValueError("Invalid S3 path format. Bucket name is required")

    # Split into bucket and key
    if "/" in path_without_scheme:
        bucket, key = path_without_scheme.split("/", 1)
    else:
        bucket = path_without_scheme
        key = ""

    # Validate bucket name is not empty
    if not bucket:
        raise ValueError("Invalid S3 path format. Bucket name cannot be empty")

    return bucket, key


def browse_s3(s3_path: str) -> FileBrowserData:
    """Browse S3 bucket/prefix and return structured data"""
    if not BOTO3_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="S3 support not available. Install boto3 to enable S3 browsing.",
        )

    try:
        bucket, prefix = _parse_s3_path(s3_path)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    try:
        # Initialize S3 client
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

    except NoCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="AWS credentials not found. Please configure AWS credentials.",
        )
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "NoSuchBucket":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"S3 bucket not found: {bucket}",
            )
        elif error_code == "AccessDenied":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to S3 bucket: {bucket}",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"S3 error: {e.response['Error']['Message']}",
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error browsing S3: {str(e)}",
        )
