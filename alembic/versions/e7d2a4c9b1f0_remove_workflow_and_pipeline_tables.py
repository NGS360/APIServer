"""Remove workflow and pipeline support: drop their tables and RBAC rows

Revision ID: e7d2a4c9b1f0
Revises: c8e4a1f72b93
Create Date: 2026-11-24

Workflows (versions, aliases, deployments, attributes) and pipelines (and
their membership and file links) are removed. The code is deleted in the same
change: api/workflow, api/pipeline, the files pipeline_id association, the
workflow:* and pipeline:* permissions, and the Omics registration settings.

Upgrade, in order:

1. RBAC rows. Removed permissions are deleted from every role. The builtin
   `workflow_admin` role is deleted together with its grants. The seeder
   (api/rbac/seed.py) reconciles permissions for roles it defines, but it never
   deletes a role it no longer defines, so without this the role would survive
   with no code behind it. See c8e4a1f72b93 for the same problem.
2. Tables, children before parents. `if_exists=True` so a database that drifted
   from the migration history still upgrades.

Data in the dropped tables is not preserved. Take a database backup before
upgrading. Downgrade recreates the empty tables; it does not restore data, and
it does not restore the RBAC rows (the seeder restores the builtin roles when
the older code next starts).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


revision: str = "e7d2a4c9b1f0"
down_revision: Union[str, Sequence[str], None] = "c8e4a1f72b93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DROP_ORDER = [
    "filepipeline",
    "pipelineworkflow",
    "pipelineattribute",
    "pipeline",
    "workflowdeployment",
    "workflowversionalias",
    "workflowversionattribute",
    "workflowversion",
    "workflowattribute",
    "workflow",
]


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text(
        "DELETE FROM role_permission "
        "WHERE permission LIKE 'workflow:%' OR permission LIKE 'pipeline:%'"
    ))
    conn.execute(sa.text(
        "DELETE FROM user_role WHERE role_id IN "
        "(SELECT id FROM role WHERE name = 'workflow_admin' AND is_builtin = 1)"
    ))
    conn.execute(sa.text(
        "DELETE FROM role_permission WHERE role_id IN "
        "(SELECT id FROM role WHERE name = 'workflow_admin' AND is_builtin = 1)"
    ))
    conn.execute(sa.text(
        "DELETE FROM role WHERE name = 'workflow_admin' AND is_builtin = 1"
    ))

    for table in _DROP_ORDER:
        op.drop_table(table, if_exists=True)


def downgrade() -> None:
    op.create_table(
        "workflow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflowattribute",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflowversion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition_uri", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),
    )
    op.create_table(
        "workflowversionattribute",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflowversion.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workflowversionalias",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflowversion.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "alias", name="uq_workflow_alias"),
    )
    op.create_table(
        "workflowdeployment",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("engine", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("external_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        # Names match 8a5d5a8bb9f6 and 38160a9eca15. Those revisions drop and
        # re-create workflowdeployment_ibfk_1 by name, so an unnamed FK here would
        # get an auto-generated name (MySQL: _ibfk_2 for the engine FK) and block
        # the "Cannot drop index 'uq_platform_name'" step on downgrade.
        sa.ForeignKeyConstraint(
            ["workflow_version_id"], ["workflowversion.id"],
            name="fk_wfdeploy_workflowversion",
        ),
        sa.ForeignKeyConstraint(
            ["engine"], ["platform.name"],
            name="workflowdeployment_ibfk_1",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_version_id", "engine", name="uq_workflowversion_engine"),
    )
    op.create_table(
        "pipeline",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("version", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "pipelineattribute",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipeline.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", "key", name="uq_pipeline_attr_key"),
    )
    op.create_table(
        "pipelineworkflow",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipeline.id"]),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pipeline_id", "workflow_id", name="uq_pipeline_workflow"),
    )
    op.create_table(
        "filepipeline",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["file.id"]),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipeline.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("file_id", "pipeline_id", name="uq_filepipeline"),
    )
