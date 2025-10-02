# Files API Architecture Diagram

## System Architecture Overview

```mermaid
graph TB
    subgraph "Client Layer"
        WEB[Web Frontend]
        API_CLIENT[API Clients]
        CLI[CLI Tools]
    end

    subgraph "API Layer"
        ROUTER[FastAPI Router]
        AUTH[Authentication]
        VALID[Validation]
    end

    subgraph "Service Layer"
        FILE_SVC[File Service]
        STORAGE_SVC[Storage Service]
        METADATA_SVC[Metadata Service]
    end

    subgraph "Storage Backends"
        LOCAL[Local Storage]
        S3[AWS S3]
        AZURE[Azure Blob]
        GCS[Google Cloud]
    end

    subgraph "Database Layer"
        FILE_TBL[(File Table)]
        PROJECT_TBL[(Project Table)]
        RUN_TBL[(Run Table)]
        PERM_TBL[(Permissions Table)]
    end

    subgraph "Search & Index"
        OPENSEARCH[OpenSearch]
        SEARCH_IDX[File Index]
    end

    WEB --> ROUTER
    API_CLIENT --> ROUTER
    CLI --> ROUTER

    ROUTER --> AUTH
    AUTH --> VALID
    VALID --> FILE_SVC

    FILE_SVC --> STORAGE_SVC
    FILE_SVC --> METADATA_SVC
    FILE_SVC --> FILE_TBL

    STORAGE_SVC --> LOCAL
    STORAGE_SVC --> S3
    STORAGE_SVC --> AZURE
    STORAGE_SVC --> GCS

    FILE_TBL -.-> PROJECT_TBL
    FILE_TBL -.-> RUN_TBL
    FILE_TBL --> PERM_TBL

    METADATA_SVC --> OPENSEARCH
    OPENSEARCH --> SEARCH_IDX
```

## Data Model Relationships

```mermaid
erDiagram
    PROJECT {
        uuid id PK
        string project_id UK
        string name
    }

    SEQUENCING_RUN {
        uuid id PK
        string barcode UK
        date run_date
        string machine_id
        string status
    }

    FILE {
        uuid id PK
        string file_id UK
        string filename
        string original_filename
        string file_path
        int file_size
        string mime_type
        string checksum
        string description
        enum file_type
        datetime upload_date
        string created_by
        enum entity_type
        string entity_id FK
        enum storage_backend
        boolean is_public
        boolean is_archived
    }

    FILE_PERMISSION {
        uuid id PK
        uuid file_id FK
        string user_id
        string group_id
        enum permission_type
        datetime granted_date
    }

    FILE_VERSION {
        uuid id PK
        uuid file_id FK
        int version_number
        string file_path
        int file_size
        string checksum
        datetime created_date
        boolean is_current
    }

    PROJECT ||--o{ FILE : "has files"
    SEQUENCING_RUN ||--o{ FILE : "has files"
    FILE ||--o{ FILE_PERMISSION : "has permissions"
    FILE ||--o{ FILE_VERSION : "has versions"
```

## API Endpoint Structure

```mermaid
graph LR
    subgraph "Generic File Operations"
        A[GET /files] --> A1[List all files]
        B[POST /files] --> B1[Upload file]
        C[GET /files/{id}] --> C1[Get file metadata]
        D[PUT /files/{id}] --> D1[Update metadata]
        E[DELETE /files/{id}] --> E1[Delete file]
        F[GET /files/{id}/download] --> F1[Download file]
    end

    subgraph "Project File Operations"
        G[GET /projects/{id}/files] --> G1[List project files]
        H[POST /projects/{id}/files] --> H1[Upload to project]
        I[GET /projects/{id}/files/{file_id}] --> I1[Get project file]
    end

    subgraph "Run File Operations"
        J[GET /runs/{barcode}/files] --> J1[List run files]
        K[POST /runs/{barcode}/files] --> K1[Upload to run]
        L[GET /runs/{barcode}/files/{file_id}] --> L1[Get run file]
    end

    subgraph "Bulk Operations"
        M[POST /files/bulk-upload] --> M1[Upload multiple]
        N[DELETE /files/bulk-delete] --> N1[Delete multiple]
    end
```

## File Upload Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant FileService
    participant StorageService
    participant Database
    participant Storage

    Client->>API: POST /projects/{id}/files
    API->>API: Validate request
    API->>FileService: upload_file()
    FileService->>FileService: Generate file_id
    FileService->>StorageService: store_file()
    StorageService->>Storage: Upload file data
    Storage-->>StorageService: Storage URI
    StorageService-->>FileService: File path
    FileService->>Database: Save file metadata
    Database-->>FileService: File record
    FileService-->>API: File metadata
    API-->>Client: Upload response
```

## File Download Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant FileService
    participant StorageService
    participant Database
    participant Storage

    Client->>API: GET /files/{id}/download
    API->>API: Check permissions
    API->>FileService: get_download_url()
    FileService->>Database: Get file metadata
    Database-->>FileService: File record
    FileService->>StorageService: generate_download_url()
    StorageService->>Storage: Create signed URL
    Storage-->>StorageService: Signed URL
    StorageService-->>FileService: Download URL
    FileService-->>API: Download URL
    API-->>Client: Redirect or URL response
```

## Storage Strategy

```mermaid
graph TB
    subgraph "File Organization"
        ROOT[Storage Root]
        ROOT --> PROJECTS[/projects/]
        ROOT --> RUNS[/runs/]
        
        PROJECTS --> PROJ_ID[/{project_id}/]
        RUNS --> RUN_ID[/{run_barcode}/]
        
        PROJ_ID --> PROJ_TYPE[/{file_type}/]
        RUN_ID --> RUN_TYPE[/{file_type}/]
        
        PROJ_TYPE --> PROJ_DATE[/{year}/{month}/]
        RUN_TYPE --> RUN_DATE[/{year}/{month}/]
        
        PROJ_DATE --> PROJ_FILE[/{file_id}_{filename}]
        RUN_DATE --> RUN_FILE[/{file_id}_{filename}]
    end

    subgraph "Storage Backends"
        LOCAL_FS[Local Filesystem]
        AWS_S3[AWS S3]
        AZURE_BLOB[Azure Blob Storage]
        GCP_STORAGE[Google Cloud Storage]
    end

    PROJ_FILE -.-> LOCAL_FS
    PROJ_FILE -.-> AWS_S3
    PROJ_FILE -.-> AZURE_BLOB
    PROJ_FILE -.-> GCP_STORAGE

    RUN_FILE -.-> LOCAL_FS
    RUN_FILE -.-> AWS_S3
    RUN_FILE -.-> AZURE_BLOB
    RUN_FILE -.-> GCP_STORAGE
```

## Security and Access Control

```mermaid
graph TB
    subgraph "Authentication"
        USER[User Request]
        AUTH_CHECK[Authentication Check]
        TOKEN[JWT Token Validation]
    end

    subgraph "Authorization"
        PERM_CHECK[Permission Check]
        ENTITY_ACCESS[Entity Access Check]
        FILE_ACCESS[File Access Check]
    end

    subgraph "File Operations"
        READ_OP[Read Operation]
        WRITE_OP[Write Operation]
        DELETE_OP[Delete Operation]
    end

    USER --> AUTH_CHECK
    AUTH_CHECK --> TOKEN
    TOKEN --> PERM_CHECK
    PERM_CHECK --> ENTITY_ACCESS
    ENTITY_ACCESS --> FILE_ACCESS
    FILE_ACCESS --> READ_OP
    FILE_ACCESS --> WRITE_OP
    FILE_ACCESS --> DELETE_OP
```

This architecture provides:

1. **Scalable Design**: Supports multiple storage backends and can handle large file volumes
2. **Flexible Associations**: Files can be linked to any entity type (projects, runs, future entities)
3. **Rich Metadata**: Comprehensive file information and categorization
4. **Security**: Multi-layered permission system
5. **Performance**: Efficient querying and caching strategies
6. **Extensibility**: Easy to add new file types, storage backends, and features