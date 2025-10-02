"""
Models for the Files API
"""
from sqlmodel import SQLModel


class FileBrowserFolder(SQLModel):
    """Folder item for file browser"""

    name: str
    date: str


class FileBrowserFile(SQLModel):
    """File item for file browser"""

    name: str
    date: str
    size: int


class FileBrowserData(SQLModel):
    """File browser data structure with separate folders and files"""

    folders: list[FileBrowserFolder]
    files: list[FileBrowserFile]
