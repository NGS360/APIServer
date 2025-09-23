"""
Models for the Runs API
"""
from typing import Optional
import uuid
from datetime import datetime, date
from enum import Enum
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict, computed_field, field_validator


class RunStatus(str, Enum):
    """Enumeration of valid sequencing run statuses"""
    IN_PROGRESS = "In Progress"
    UPLOADING = "Uploading"
    READY = "Ready"
    RESYNC = "Resync"


class SequencingRun(SQLModel, table=True):
    """
    This class/table represents a sequencing run
    """

    # Searchable is a new field used for Elasticsearch
    # This field is iterated on to identify what fields are searchable
    # or inserted into the ElasticSearch index.
    __searchable__ = ["barcode", "experiment_name"]

    id: uuid.UUID | None = Field(default_factory=uuid.uuid4, primary_key=True)
    run_date: date
    machine_id: str = Field(max_length=25)
    run_number: int
    flowcell_id: str = Field(max_length=25)
    experiment_name: str | None = Field(default=None, max_length=255)
    run_folder_uri: str | None = Field(default=None, max_length=255)
    status: RunStatus | None = Field(default=None)
    run_time: str | None = Field(default=None, max_length=4)

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def is_data_valid(data):
        ''' A Run must have an experiment_name and a run_folder_uri to be valid '''
        for field in ["experiment_name", "run_folder_uri"]:
            if field not in data:
                return False
        return True

    @staticmethod
    def parse_barcode(barcode: str):
        """
        Converts a barcode to its parts

        :param barcode: Barcode in the form of
                     <YYMMDD>_<machineid>_<zero padded run number>_<flowcell>
                  or ONT run id in the form of
                     <YYYYMMDD>_<HHMM>_<machineid>_<flowcell>_<run string>
        :return: 5 parts (run_date, run_time, machine_id, run_number, flowcell_id) or None
        """
        # Define (default) return values
        run_date, run_time, machine_id, run_number, flowcell_id = (None, None, None, None, None)

        # Split the barcode into its parts
        run_id_fields = barcode.split("_")
        if len(run_id_fields) not in [4, 5]:
            return (None, None, None, None, None)

        # illumina run id has 4 fields
        if len(run_id_fields) == 4:
            run_date = datetime.strptime(run_id_fields[0], "%y%m%d").date()
            machine_id = run_id_fields[1]

            # Convert run_number to an integer, as it is padded with a leading zero
            # in the run_barcode
            # run_number = int(barcode_items[2])
            run_number = run_id_fields[2]

            flowcell_id = run_id_fields[3]
            run_time = None

        # ONT will have 5 fields
        if len(run_id_fields) == 5:
            run_date = datetime.strptime(run_id_fields[0], "%Y%m%d").date()
            run_time = run_id_fields[1]
            machine_id = run_id_fields[2]
            run_number = run_id_fields[4]
            flowcell_id = run_id_fields[3]

        return (run_date, run_time, machine_id, run_number, flowcell_id)

    @computed_field
    @property
    def barcode(self) -> str:
        ''' Generates a barcode from the run fields '''
        if self.run_time is None:
            run_number = str(self.run_number).zfill(4)
            run_date = self.run_date.strftime("%y%m%d")
            return f"{run_date}_{self.machine_id}_{run_number}_{self.flowcell_id}"
        run_date = self.run_date.strftime("%Y%m%d")
        return f"{run_date}_{self.run_time}_{self.machine_id}_{self.flowcell_id}_{self.run_number}"

    def to_dict(self):
        ''' Returns a dictionary representation of the object '''
        data = {
            "id": self.id,
            "run_date": self.run_date.strftime("%Y-%m-%d") if self.run_date else None,
            "machine_id": self.machine_id,
            "run_number": self.run_number,
            "run_time": self.run_time,
            "flowcell_id": self.flowcell_id,
            "experiment_name": self.experiment_name,
            "run_folder_uri": self.run_folder_uri,
            "status": self.status.value if self.status else None,
            "barcode": self.barcode,
        }
        return data

    def from_dict(self, data):
        ''' Updates the object from a dictionary '''
        for field in data:
            setattr(self, field, data[field])

    def __repr__(self):
        return f"<SequencingRun {self.id}>"


class SequencingRunCreate(SQLModel):
    run_date: date
    machine_id: str
    run_number: int
    flowcell_id: str
    experiment_name: str | None = None
    run_folder_uri: str | None = None
    status: RunStatus | None = None
    run_time: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator('run_time', mode='before')
    @classmethod
    def preprocess_run_time(cls, v):
        """Convert empty string to None before validation"""
        return None if v == "" else v

    @field_validator('run_time')
    @classmethod
    def validate_run_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None

        if not isinstance(v, str) or len(v) != 4 or not v.isdigit():
            raise ValueError('run_time must be exactly 4 digits (HHMM format)')

        hours, minutes = int(v[:2]), int(v[2:])
        if not (0 <= hours <= 23) or not (0 <= minutes <= 59):
            raise ValueError('Hours must be 00-23, minutes must be 00-59')

        return v


class SequencingRunUpdateRequest(SQLModel):
    run_status: RunStatus

    model_config = ConfigDict(extra="forbid")


class SequencingRunPublic(SQLModel):
    run_date: date
    machine_id: str
    run_number: int
    flowcell_id: str
    experiment_name: str | None
    run_folder_uri: str | None
    status: RunStatus | None
    run_time: str | None
    barcode: str | None


class SequencingRunsPublic(SQLModel):
    data: list[SequencingRunPublic]
    total_items: int
    total_pages: int
    current_page: int
    per_page: int
    has_next: bool
    has_prev: bool


class IlluminaSampleSheetResponseModel(SQLModel):
    Summary: dict[str, str] | None = None
    Header: dict[str, str] | None = None
    Reads: list[int] | None = None
    Settings: dict[str, str] | None = None
    Data: list[dict[str, str]] | None = None
    DataCols: list[str] | None = None


# Helper types for IlluminaMetricsResponseModel
class ReadMetricsType(SQLModel):
    ReadNumber: int | None = None
    Yield: int | None = None
    YieldQ30: int | None = None
    QualityScoreSum: int | None = None
    TrimmedBases: int | None = None


class ReadInfo(SQLModel):
    Number: int | None = None
    NumCycles: int | None = None
    IsIndexedRead: bool | None = None


class ReadInfosForLane(SQLModel):
    LaneNumber: int | None = None
    ReadInfos: list[ReadInfo] | None = None


class IndexMetric(SQLModel):
    IndexSequence: str | None = None
    MismatchCounts: dict[str, int] | None = None


class DemuxResult(SQLModel):
    SampleId: str
    SampleName: str | None = None
    IndexMetrics: list[IndexMetric] | None = None
    NumberReads: int = 0
    Yield: int | None = None
    ReadMetrics: list[ReadMetricsType] = None


class UndeterminedType(SQLModel):
    NumberReads: int | None = None
    Yield: int | None = None
    ReadMetrics: list[ReadMetricsType] | None = None


class ConversionResult(SQLModel):
    LaneNumber: int
    TotalClustersRaw: int
    TotalClustersPF: int
    Yield: int | None = None
    DemuxResults: list[DemuxResult] | None = None
    Undetermined: UndeterminedType | None = None


class UnknownBarcode(SQLModel):
    Lane: int | None = None
    Barcodes: dict[str, int] | None = None


class IlluminaMetricsResponseModel(SQLModel):
    Flowcell: str | None = None
    RunNumber: int | None = None
    RunId: str | None = None
    ReadInfosForLanes: list[ReadInfosForLane] | None = None
    ConversionResults: list[ConversionResult] | None = None
    UnknownBarcodes: list[UnknownBarcode] | None = None
