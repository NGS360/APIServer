"""Unit tests for api.samples.parsing — CSV/TSV file → SampleCreate parsing."""

import pytest

from api.samples.parsing import parse_sample_file


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestParseSampleFileHappyPath:
    """Basic parsing of well-formed files."""

    def test_parse_csv_basic(self):
        """Test that a standard CSV with SampleID and attribute columns
        produces SampleCreate objects with correct sample_id and attributes
        using the original column headers as keys."""
        content = (
            "SampleID,Tissue,Condition\n"
            "S001,Liver,Healthy\n"
            "S002,Heart,Diseased\n"
        ).encode()

        result = parse_sample_file(content, "samples.csv")

        assert len(result) == 2
        assert result[0].sample_id == "S001"
        assert result[1].sample_id == "S002"

        # Attributes should use original column headers
        attrs_0 = {a.key: a.value for a in result[0].attributes}
        assert attrs_0 == {"Tissue": "Liver", "Condition": "Healthy"}

        attrs_1 = {a.key: a.value for a in result[1].attributes}
        assert attrs_1 == {"Tissue": "Heart", "Condition": "Diseased"}

    def test_parse_tsv_basic(self):
        """Test that a tab-delimited file with 'Sample ID' header is
        auto-detected and parsed into SampleCreate objects with correct
        sample_id and attributes."""
        content = (
            "Sample ID\tTissue\tCondition\n"
            "S001\tLiver\tHealthy\n"
            "S002\tHeart\tDiseased\n"
        ).encode()

        result = parse_sample_file(content, "samples.tsv")

        assert len(result) == 2
        assert result[0].sample_id == "S001"
        attrs = {a.key: a.value for a in result[0].attributes}
        assert attrs == {"Tissue": "Liver", "Condition": "Healthy"}

    def test_parse_txt_extension(self):
        """Test that a file with .txt extension is accepted and parsed
        into a SampleCreate object."""
        content = (
            "SampleID,Tissue\n"
            "S001,Liver\n"
        ).encode()

        result = parse_sample_file(content, "samples.txt")
        assert len(result) == 1
        assert result[0].sample_id == "S001"

    def test_parse_sampleid_only_file(self):
        """Test that a file with only a SampleID column produces
        SampleCreate objects with attributes set to None."""
        content = (
            "SampleID\n"
            "S001\n"
            "S002\n"
            "S003\n"
        ).encode()

        result = parse_sample_file(content, "samples.csv")

        assert len(result) == 3
        assert result[0].sample_id == "S001"
        assert result[0].attributes is None
        assert result[1].sample_id == "S002"
        assert result[2].sample_id == "S003"


# ---------------------------------------------------------------------------
# Column normalization tests
# ---------------------------------------------------------------------------


class TestColumnNormalization:
    """Verify case-insensitive, underscore/space-insensitive column matching."""

    def test_parse_lowercase_sampleid(self):
        """Test that the all-lowercase column header 'sampleid' is
        recognized as the sample identifier column."""
        content = b"sampleid,Tissue\nS001,Liver\n"
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"

    def test_parse_underscore_variant(self):
        """Test that the underscore variant 'Sample_ID' is recognized
        as the sample identifier column."""
        content = b"Sample_ID,Tissue\nS001,Liver\n"
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"

    def test_parse_mixed_case(self):
        """Test that the all-uppercase variant 'SAMPLEID' is recognized
        as the sample identifier column."""
        content = b"SAMPLEID,Tissue\nS001,Liver\n"
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"

    def test_parse_space_variant(self):
        """Test that the space-separated variant 'Sample ID' is recognized
        as the sample identifier column."""
        content = b"Sample ID,Tissue\nS001,Liver\n"
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"

    def test_parse_preserves_original_attribute_keys(self):
        """Test that non-SampleID columns retain their original casing
        and formatting as attribute keys in the parsed output."""
        content = (
            "SampleID,Tissue_Type,assay_method,READ COUNT\n"
            "S001,FFPE,WES,12345\n"
        ).encode()

        result = parse_sample_file(content, "test.csv")
        attrs = {a.key: a.value for a in result[0].attributes}

        # Original headers preserved exactly
        assert "Tissue_Type" in attrs
        assert "assay_method" in attrs
        assert "READ COUNT" in attrs
        assert attrs["Tissue_Type"] == "FFPE"
        assert attrs["assay_method"] == "WES"
        assert attrs["READ COUNT"] == "12345"


# ---------------------------------------------------------------------------
# Empty cell handling
# ---------------------------------------------------------------------------


class TestEmptyCellHandling:
    """Verify that empty/blank cells produce Attribute(value='') so the
    service layer can distinguish 'column present, value blank' from
    'column absent'."""

    def test_parse_includes_empty_cells(self):
        """Test that empty cells in attribute columns are included as
        Attribute(key=col, value='') so downstream code can detect
        that the column was present but the value was blank."""
        content = (
            "SampleID,Tissue,Condition\n"
            "S001,Liver,\n"
            "S002,,Diseased\n"
        ).encode()

        result = parse_sample_file(content, "test.csv")

        # S001: Tissue=Liver, Condition=""
        attrs_0 = {a.key: a.value for a in result[0].attributes}
        assert attrs_0 == {"Tissue": "Liver", "Condition": ""}

        # S002: Tissue="", Condition=Diseased
        attrs_1 = {a.key: a.value for a in result[1].attributes}
        assert attrs_1 == {"Tissue": "", "Condition": "Diseased"}

    def test_all_cells_empty_yields_empty_value_attributes(self):
        """Test that a row where all attribute cells are empty produces
        Attribute entries with value='' for each column."""
        content = (
            "SampleID,Tissue,Condition\n"
            "S001,,\n"
        ).encode()

        result = parse_sample_file(content, "test.csv")
        attrs = {a.key: a.value for a in result[0].attributes}
        assert attrs == {"Tissue": "", "Condition": ""}


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------


class TestParsingErrors:
    """Verify that validation errors raise ValueError with clear messages."""

    def test_parse_unsupported_extension(self):
        """Test that a file with an unsupported extension (.xlsx) raises
        ValueError with a message listing the allowed extensions."""
        content = b"SampleID\nS001\n"
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_sample_file(content, "samples.xlsx")

    def test_parse_no_extension(self):
        """Test that a filename with no extension raises ValueError
        indicating an unsupported file type."""
        content = b"SampleID\nS001\n"
        with pytest.raises(ValueError, match="Unsupported file type"):
            parse_sample_file(content, "samples")

    def test_parse_missing_sampleid_column(self):
        """Test that a file without any recognized SampleID column
        raises ValueError mentioning the expected column name."""
        content = b"Name,Tissue\nS001,Liver\n"
        with pytest.raises(ValueError, match="SampleID"):
            parse_sample_file(content, "test.csv")

    def test_parse_duplicate_sample_names(self):
        """Test that a file containing duplicate sample names raises
        ValueError identifying the duplicate name and row number."""
        content = (
            "SampleID,Tissue\n"
            "S001,Liver\n"
            "S001,Heart\n"
        ).encode()
        with pytest.raises(ValueError, match="duplicate sample name 'S001'"):
            parse_sample_file(content, "test.csv")

    def test_parse_empty_file(self):
        """Test that an empty file (zero bytes) raises ValueError
        indicating the file is empty."""
        with pytest.raises(ValueError, match="empty"):
            parse_sample_file(b"", "test.csv")

    def test_parse_headers_only_no_data(self):
        """Test that a file containing only a header row and no data
        rows raises ValueError indicating no data rows were found."""
        content = b"SampleID,Tissue\n"
        with pytest.raises(ValueError, match="no data rows"):
            parse_sample_file(content, "test.csv")

    def test_parse_empty_sample_name(self):
        """Test that a row with an empty sample name cell raises
        ValueError identifying the row with the empty name."""
        content = (
            "SampleID,Tissue\n"
            ",Liver\n"
        ).encode()
        with pytest.raises(ValueError, match="empty sample name"):
            parse_sample_file(content, "test.csv")


# ---------------------------------------------------------------------------
# BOM / encoding handling
# ---------------------------------------------------------------------------


class TestEncodingHandling:
    """Verify BOM and encoding edge cases."""

    def test_parse_utf8_bom(self):
        """Test that a UTF-8 file with a byte-order mark (BOM) is parsed
        correctly with the BOM stripped from column headers."""
        bom = b"\xef\xbb\xbf"
        content = bom + b"SampleID,Tissue\nS001,Liver\n"
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"
        attrs = {a.key: a.value for a in result[0].attributes}
        assert attrs == {"Tissue": "Liver"}

    def test_parse_latin1_encoding(self):
        """Test that a Latin-1 encoded file with non-ASCII characters
        is decoded and parsed correctly."""
        content = "SampleID,Tissue\nS001,Lébér\n".encode("latin-1")
        result = parse_sample_file(content, "test.csv")
        assert result[0].sample_id == "S001"
        attrs = {a.key: a.value for a in result[0].attributes}
        assert attrs["Tissue"] == "Lébér"
