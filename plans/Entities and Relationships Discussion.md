# Entities and Relationships Discussion
A Project can have Sample(s)

A Sample is associated with exactly 1 project
A Sample can contain files from more than 1 sequencing run
A Sample can have QCMetrics associated with it.

A SequencingRun produces/generates files associated with Samples
A SequencingRun can contain Samples from 1 or more Projects
A SequencingRun can have QCMetrics associated with it.

Workflow - A directed graph of steps to transform data (e.g. CWL or Nextflow workflow)
WorkflowRun - An execution of a workflow (user executed, platform executed on, inputs, outputs, etc)
WorkflowRun can have QCMetrics associated with it.

Pipeline - Consists of 1 or more workflows to transform inputs to outputs associated with some business logic.

QCMetric - A QCMetric is a structured, versioned measurement that quantitatively evaluates quality attributes of a biological or computational artifact, produced at a defined processing stage and scoped to a specific entity (e.g., SequencingRun, Sample, WorkflowRun).

We need to represent QCMetrics that are produced/associated with more than 1 sample, e.g. TMB (from a WGS tumor/normal pair) -
A QCMetric is a structured quantitative measurement generated at a defined processing stage and scoped to a QCEntity, where a QCEntity may represent one or more domain entities participating in the measurement.

File - Can be associated with any of these top-level entities.



```mermaid

    erDiagram

        PROJECT ||--o{ SAMPLE : has

        SAMPLE }o--o{ SEQUENCING_RUN : participates_in

        SEQUENCING_RUN ||--o{ FILE : produces
        SAMPLE ||--o{ FILE : has
        WORKFLOW_RUN ||--o{ FILE : outputs
        PIPELINE ||--o{ FILE : generates
        PROJECT ||--o{ FILE : contains

        WORKFLOW ||--o{ WORKFLOW_RUN : executed_as
        PIPELINE ||--o{ WORKFLOW : consists_of

        QC_ENTITY ||--o{ QC_ENTITY_MEMBER : has_members
        SAMPLE ||--o{ QC_ENTITY_MEMBER : member_of
        SEQUENCING_RUN ||--o{ QC_ENTITY_MEMBER : member_of
        WORKFLOW_RUN ||--o{ QC_ENTITY_MEMBER : member_of
        PROJECT ||--o{ QC_ENTITY_MEMBER : member_of
        PIPELINE ||--o{ QC_ENTITY_MEMBER : member_of

        QC_ENTITY ||--o{ QC_METRIC : has

        PROJECT {
            uuid id
            string name
        }

        SAMPLE {
            uuid id
            uuid project_id
            string name
        }

        SEQUENCING_RUN {
            uuid id
            string platform
            datetime run_date
        }

        WORKFLOW {
            uuid id
            string name
            string version
        }

        WORKFLOW_RUN {
            uuid id
            uuid workflow_id
            datetime executed_at
            string status
        }

        PIPELINE {
            uuid id
            string name
            string version
        }

        FILE {
            uuid id
            string path
            string file_type
        }

        QC_ENTITY {
            uuid id
            string entity_scope
            string entity_type
        }

        QC_ENTITY_MEMBER {
            uuid qc_entity_id
            uuid member_id
            string member_type
            string role
        }

        QC_METRIC {
            uuid id
            uuid qc_entity_id
            string name
            float value
            string unit
            string tool_name
            string tool_version
            string pipeline_version
            datetime calculated_at
        }

```
 

 _Originally posted by @golharam in [#149](https://github.com/NGS360/APIServer/issues/149#issuecomment-3947229010)_