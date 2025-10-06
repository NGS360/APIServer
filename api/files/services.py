"""
Services for the Files API
"""

from fastapi import HTTPException, status
from pathlib import Path
from datetime import datetime

try:
    import boto3
    from botocore.exceptions import NoCredentialsError, ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from api.files.models import FileBrowserData, FileBrowserFile, FileBrowserFolder


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


def _list_s3(s3_path: str, storage_root: str, s3_client=None) -> FileBrowserData:
    """
    Browse S3 bucket/prefix and return structured data.
    
    Args:
        s3_path: The S3 path to list
        storage_root: The storage root path (s3://) that acts as the boundary for navigation.
                     All paths must be within this root.
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
        root_bucket, root_prefix = _parse_s3_path(storage_root)
        
        # Security check: ensure path is within storage root
        if bucket != root_bucket:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: path is outside storage root bucket",
            )
        
        if root_prefix and not prefix.startswith(root_prefix):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: path is outside storage root prefix",
            )
            
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    try:
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


def _list_local_storage(
    directory_path: str, storage_root: str = "storage"
) -> FileBrowserData:
    """
    List files and folders in local storage at the specified directory path.
    
    Args:
        directory_path: The path to list files from. Can be absolute or relative.
        storage_root: The absolute root directory that acts as the boundary for navigation.
                     All paths must be within this directory.
    """
    # Convert both paths to absolute and resolved paths
    directory_path = Path(directory_path).resolve()
    storage_root = Path(storage_root).resolve()

    # Security check: ensure the resolved path is within storage_root
    try:
        directory_path.relative_to(storage_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: path escapes storage root",
        ) from exc

    # Check if directory exists and is accessible
    if not directory_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Directory not found: {str(directory_path)}",
        )

    if not directory_path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a directory: {str(directory_path)}",
        )

    folders = []
    files = []

    try:
        # List directory contents
        for item in directory_path.iterdir():
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

    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied accessing directory: {directory_path}",
        ) from exc

    # Sort folders and files by name
    folders.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())

    return FileBrowserData(folders=folders, files=files)


def list_files(uri: str, storage_root: str, s3_client=None) -> FileBrowserData:
    """
    List files and folders at the specified URI.
    
    Args:
        uri: The URI to list files from. Can be an S3 URI (s3://) or a local path.
        storage_root: The root directory that acts as the boundary for navigation.
                     For local paths: absolute filesystem path (e.g., /app/storage/folder)
                     For S3: s3:// URI (e.g., s3://bucket/prefix)
                     All access will be restricted to within this root.
        s3_client: Optional boto3 S3 client for S3 operations.
    
    Returns:
        FileBrowserData containing the list of files and folders.
    
    Security:
        - For local storage: No navigation above storage_root is allowed
        - For S3: No navigation outside storage_root bucket/prefix is allowed
    """
    if uri.startswith("s3://"):
        if not storage_root.startswith("s3://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Storage root must be an S3 URI (s3://) for S3 paths",
            )
        try:
            return _list_s3(uri, storage_root=storage_root, s3_client=s3_client)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    return _list_local_storage(uri, storage_root=storage_root)
