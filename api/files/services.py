"""
Services for managing files.
"""

import hashlib
import secrets
import string
from pathlib import Path
from sqlmodel import select, Session, func
from pydantic import PositiveInt
from fastapi import HTTPException, status

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
)


def generate_file_id() -> str:
    """Generate a unique file ID"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(12))


def generate_file_path(
    entity_type: EntityType, entity_id: str, file_type: FileType, filename: str
) -> str:
    """Generate a structured file path"""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    year = now.strftime("%Y")
    month = now.strftime("%m")

    # Create path structure: /{entity_type}/{entity_id}/{file_type}/{year}/{month}/{filename}
    path_parts = [
        entity_type.value,
        entity_id,
        file_type.value,
        year,
        month,
        filename
    ]
    return "/".join(path_parts)


def calculate_file_checksum(file_content: bytes) -> str:
    """Calculate SHA-256 checksum of file content"""
    return hashlib.sha256(file_content).hexdigest()


def get_mime_type(filename: str) -> str:
    """Get MIME type based on file extension"""
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


def create_file(
    session: Session,
    file_create: FileCreate,
    file_content: bytes | None = None,
    storage_root: str = "storage"
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
        f"{file_id}_{file_create.filename}"
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
        storage_backend=StorageBackend.LOCAL
    )

    # Store file content if provided
    if file_content:
        full_path = Path(storage_root) / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(file_content)

    # Save to database
    session.add(file_record)
    session.commit()
    session.refresh(file_record)

    return file_record


def get_file(session: Session, file_id: str) -> File:
    """Get a file by its file_id"""
    file_record = session.exec(
        select(File).where(File.file_id == file_id)
    ).first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with id {file_id} not found"
        )

    return file_record


def get_file_by_id(session: Session, id: str) -> File:
    """Get a file by its internal UUID"""
    file_record = session.exec(
        select(File).where(File.id == id)
    ).first()

    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with internal id {id} not found"
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
    sort_order: str = "desc"
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
                (File.filename.ilike(search_term)) |
                (File.description.ilike(search_term))
            )

    # Get total count
    total_count = session.exec(
        select(func.count()).select_from(query.subquery())
    ).one()

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
            checksum=file.checksum
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
        has_prev=page > 1
    )


def get_file_content(session: Session, file_id: str, storage_root: str = "storage") -> bytes:
    """Get file content from storage"""
    file_record = get_file(session, file_id)

    full_path = Path(storage_root) / file_record.file_path
    if not full_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File content not found at {file_record.file_path}"
        )

    with open(full_path, "rb") as f:
        return f.read()


def list_files_for_entity(
    session: Session,
    entity_type: EntityType,
    entity_id: str,
    page: PositiveInt = 1,
    per_page: PositiveInt = 20,
    file_type: FileType | None = None
) -> FilesPublic:
    """List files for a specific entity (project or run)"""
    filters = FileFilters(
        entity_type=entity_type,
        entity_id=entity_id,
        file_type=file_type
    )

    return list_files(
        session=session,
        filters=filters,
        page=page,
        per_page=per_page
    )


def get_file_count_for_entity(
    session: Session,
    entity_type: EntityType,
    entity_id: str
) -> int:
    """Get the count of files for a specific entity"""
    count = session.exec(
        select(func.count(File.id)).where(
            File.entity_type == entity_type,
            File.entity_id == entity_id,
            ~File.is_archived
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
