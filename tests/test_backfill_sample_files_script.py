"""
Tests for the mate tag scripts/backfill_sample_files.py puts on each FASTQ.

The samplesheet builder places a file in the R1 or R2 column only from its
tags["mate"], so a wrong tag here silently produces a broken pair rather than an
error. The case that motivated these tests: a delivery named
<sample>_1.clipped.fastq.gz / _2.clipped.fastq.gz, which matched no read-pair
pattern and fell through to the single-end rule -- both mates tagged R1.
"""
import pytest

from scripts import backfill_sample_files as script


@pytest.mark.parametrize("filename, mate", [
    # Illumina demux naming
    ("S1_S3_L001_R1_001.fastq.gz", "R1"),
    ("S1_S3_L001_R2_001.fastq.gz", "R2"),
    ("S1_R2.fastq.gz", "R2"),
    # dot-delimited
    ("S1.R2.fastq.gz", "R2"),
    # SRA / ENA read-pair naming, compressed or not
    ("SRR100_1.fastq.gz", "R1"),
    ("SRR100_2.fastq.gz", "R2"),
    ("SRR100_2.fq", "R2"),
])
def test_read_pair_names(filename, mate):
    assert script.extract_mate_from_filename(filename) == mate


@pytest.mark.parametrize("filename, mate", [
    ("S1_1.clipped.fastq.gz", "R1"),
    ("S1_2.clipped.fastq.gz", "R2"),
    ("S1_R2.clipped.fastq.gz", "R2"),
    ("S1_R2_001.trimmed.fastq.gz", "R2"),
    ("S1.R2.clipped.fq.gz", "R2"),
])
def test_processing_step_word_before_extension(filename, mate):
    assert script.extract_mate_from_filename(filename) == mate


@pytest.mark.parametrize("filename", [
    "sample.fastq.gz",
    "sample.clipped.fastq.gz",
])
def test_fastq_without_read_token_is_single_end_r1(filename):
    assert script.extract_mate_from_filename(filename) == "R1"


def test_non_fastq_has_no_mate():
    assert script.extract_mate_from_filename("sample.bam") is None
