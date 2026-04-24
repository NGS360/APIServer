"""
Parse CSV/TSV files into SampleCreate objects for bulk sample upload.

This module is a pure parsing layer — no database or FastAPI dependencies.
It accepts raw file bytes + filename and returns a list of SampleCreate objects
ready for the bulk_create_samples() service.
"""

import csv
import io
import re
from typing import List

from api.samples.models import SampleCreate, Attribute


# ---------------------------------------------------------------------------
# Column normalization
# ---------------------------------------------------------------------------

_SAMPLENAME_CANONICAL = "samplename"

ALLOWED_EXTENSIONS = {"csv", "tsv", "txt"}


def _normalize_header(header: str) -> str:
    """
    Normalize a column header for matching:
    lowercase, strip underscores and spaces.

    Examples:
        "Sample_Name"  → "samplename"
        "SampleName"   → "samplename"
        "SAMPLE NAME"  → "samplename"
        "Tissue Type"  → "tissuetype"
    """
    return re.sub(r"[_\s]", "", header.strip().lower())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_sample_file(
    file_content: bytes,
    filename: str,
) -> List[SampleCreate]:
    """
    Parse a CSV/TSV file into a list of SampleCreate objects.

    - Validates file extension is .csv, .tsv, or .txt
    - Detects delimiter via csv.Sniffer
    - Normalizes column headers for matching (case-insensitive,
      underscore/space-insensitive)
    - Validates required 'samplename' column exists
    - Validates no duplicate sample names
    - Skips empty cell values in attributes
    - Preserves original column header as attribute key

    Args:
        file_content: Raw bytes of the uploaded file
        filename: Original filename (used for extension validation)

    Returns:
        List of SampleCreate objects

    Raises:
        ValueError: On validation failures (bad extension, missing
                    samplename column, duplicate sample names, empty file)
    """
    # ── Validate extension ────────────────────────────────────────────
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '.{ext}'. "
            f"Allowed extensions: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # ── Decode content ────────────────────────────────────────────────
    try:
        text = file_content.decode("utf-8-sig")  # handles BOM
    except UnicodeDecodeError:
        try:
            text = file_content.decode("latin-1")
        except UnicodeDecodeError:
            raise ValueError("Unable to decode file — expected UTF-8 or Latin-1 encoding")

    text = text.strip()
    if not text:
        raise ValueError("File is empty")

    # ── Detect delimiter ──────────────────────────────────────────────
    try:
        sample = text[:8192]  # sniff first 8KB
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
    except csv.Error:
        # Default to comma if sniffer fails
        dialect = csv.excel

    # ── Parse ─────────────────────────────────────────────────────────
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)

    if not reader.fieldnames:
        raise ValueError("File has no column headers")

    # Build mapping: normalized_header → original_header
    original_headers = list(reader.fieldnames)
    normalized_map = {
        _normalize_header(h): h for h in original_headers
    }

    # ── Validate samplename column exists ─────────────────────────────
    if _SAMPLENAME_CANONICAL not in normalized_map:
        raise ValueError(
            "File must have a column named 'SampleName' or 'Sample_Name' "
            "(case-insensitive). "
            f"Found columns: {', '.join(original_headers)}"
        )

    samplename_original = normalized_map[_SAMPLENAME_CANONICAL]

    # Attribute columns = everything except samplename
    attribute_columns = [
        h for h in original_headers
        if _normalize_header(h) != _SAMPLENAME_CANONICAL
    ]

    # ── Iterate rows ──────────────────────────────────────────────────
    samples: List[SampleCreate] = []
    seen_names: set[str] = set()

    for row_idx, row in enumerate(reader, start=2):  # row 1 is header
        raw_name = row.get(samplename_original, "")
        if raw_name is None:
            raw_name = ""
        sample_name = raw_name.strip()

        if not sample_name:
            raise ValueError(
                f"Row {row_idx}: empty sample name"
            )

        if sample_name in seen_names:
            raise ValueError(
                f"Row {row_idx}: duplicate sample name '{sample_name}'"
            )
        seen_names.add(sample_name)

        # Build attributes from remaining columns.
        # Empty cells are included as value="" so the service layer
        # can delete previously-set attributes when the column is
        # present but the value is blank.
        attributes: List[Attribute] | None = None
        if attribute_columns:
            attr_list = []
            for col in attribute_columns:
                value = row.get(col, "")
                if value is None:
                    value = ""
                value = value.strip()
                attr_list.append(Attribute(key=col, value=value))
            attributes = attr_list if attr_list else None

        samples.append(
            SampleCreate(sample_id=sample_name, attributes=attributes)
        )

    if not samples:
        raise ValueError("File contains headers but no data rows")

    return samples
