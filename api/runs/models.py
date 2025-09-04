"""
Models for the Runs API
"""

import uuid
from datetime import datetime, date
from sqlmodel import SQLModel, Field
from pydantic import ConfigDict, computed_field


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
    s3_run_folder_path: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=50)
    run_time: str | None = Field(default=None, max_length=4)

    model_config = ConfigDict(from_attributes=True)

    @staticmethod
    def is_data_valid(data):
        for field in ["experiment_name", "s3_run_folder_path"]:
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
        if self.run_time is None:
            run_number = str(self.run_number).zfill(4)
            run_date = self.run_date.strftime("%y%m%d")
            return f"{run_date}_{self.machine_id}_{run_number}_{self.flowcell_id}"
        run_date = self.run_date.strftime("%Y%m%d")
        return f"{run_date}_{self.run_time}_{self.machine_id}_{self.flowcell_id}_{self.run_number}"

    def to_dict(self):
        data = {
            "id": self.id,
            "run_date": self.run_date.strftime("%Y-%m-%d") if self.run_date else None,
            "machine_id": self.machine_id,
            "run_number": self.run_number,
            "run_time": self.run_time,
            "flowcell_id": self.flowcell_id,
            "experiment_name": self.experiment_name,
            "s3_run_folder_path": self.s3_run_folder_path,
            "status": self.status,
            "barcode": self.barcode,
        }
        return data

    def from_dict(self, data):
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
    s3_run_folder_path: str | None = None
    status: str | None = None
    run_time: str | None = None

    model_config = ConfigDict(extra="forbid")


class SequencingRunPublic(SQLModel):
    run_date: date
    machine_id: str
    run_number: int
    flowcell_id: str
    experiment_name: str | None
    s3_run_folder_path: str | None
    status: str | None
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
