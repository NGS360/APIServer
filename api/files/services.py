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


def _list_s3(s3_path: str, s3_client=None) -> FileBrowserData:
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
        directory_path: str,
        storage_root: str = "storage") -> FileBrowserData:
    """
    List files and folders in local storage at the specified directory path.
    """
    # Construct the full path, relative to storage_root
    #if os.path.isabs(directory_path):
    #    full_path = Path(directory_path)
    #else:
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

    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied accessing directory: {directory_path}",
        ) from exc

    # Sort folders and files by name
    folders.sort(key=lambda x: x.name.lower())
    files.sort(key=lambda x: x.name.lower())

    return FileBrowserData(folders=folders, files=files)


def list_files(uri: str, s3_client=None) -> FileBrowserData:
    """
    List files and folders at the specified URI.
    """
    if uri.startswith("s3://"):
        return _list_s3(uri, s3_client=s3_client)

    return _list_local_storage(uri)
