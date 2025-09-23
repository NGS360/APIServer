# S3 Bulk File Registration

This script allows you to register existing S3 files in your database without moving them. Files remain in S3 but become discoverable through the Files API.

## Prerequisites

1. **AWS Credentials**: Configure AWS credentials using one of these methods:
   - AWS CLI: `aws configure`
   - Environment variables: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
   - IAM roles (if running on EC2)
   - AWS credentials file

2. **Required Permissions**: Your AWS credentials need the following S3 permissions:
   - `s3:ListBucket` - to list objects in buckets
   - `s3:GetObject` - to read object metadata
   - `s3:HeadBucket` - to verify bucket access

3. **Python Dependencies**: Install boto3 if not already installed:
   ```bash
   pip install boto3
   ```

## Usage Examples

### 1. Single Bucket Registration

Register all files from a specific bucket:
```bash
python scripts/register_s3_files.py --bucket my-ngs-data-bucket
```

Register files with a specific prefix:
```bash
python scripts/register_s3_files.py --bucket my-bucket --prefix projects/
```

### 2. Dry Run Mode

See what would be registered without making changes:
```bash
python scripts/register_s3_files.py --bucket my-bucket --dry-run
```

### 3. Configuration File Mode

For multiple buckets or complex setups, use a configuration file:

1. Create a configuration file (copy from `s3_registration_config.sample.json`):
   ```bash
   cp scripts/s3_registration_config.sample.json my_s3_config.json
   ```

2. Edit the configuration file with your bucket details:
   ```json
   {
     "buckets": [
       {
         "name": "my-ngs-data-bucket",
         "prefix": "projects/",
         "entity_patterns": {
           "project": "projects/([^/]+)",
           "run": "runs/([^/]+)"
         }
       }
     ],
     "dry_run": false
   }
   ```

3. Run with the configuration:
   ```bash
   python scripts/register_s3_files.py --config my_s3_config.json
   ```

### 4. Generate Sample Configuration

Create a sample configuration file:
```bash
python scripts/register_s3_files.py --create-config
```

## Configuration File Format

```json
{
  "buckets": [
    {
      "name": "bucket-name",
      "prefix": "optional/prefix/",
      "entity_patterns": {
        "project": "regex_pattern_to_extract_project_id",
        "run": "regex_pattern_to_extract_run_id"
      }
    }
  ],
  "dry_run": true
}
```

### Entity Patterns

Entity patterns are regex patterns used to extract project or run IDs from S3 object keys:

- `"project": "projects/([^/]+)"` - Extracts project ID from paths like `projects/PROJ001/file.fastq`
- `"run": "runs/([^/]+)"` - Extracts run ID from paths like `runs/RUN123/data.bam`

The captured group `([^/]+)` becomes the entity ID.

## File Type Detection

The script automatically detects file types based on extensions:

| Extension | File Type |
|-----------|-----------|
| `.fastq`, `.fastq.gz`, `.fq`, `.fq.gz` | FASTQ |
| `.bam`, `.sam` | BAM |
| `.vcf`, `.vcf.gz` | VCF |
| `.csv`, `.xlsx` | SAMPLESHEET |
| `.json` | METRICS |
| `.html`, `.pdf` | REPORT |
| `.log`, `.txt` | LOG |
| `.png`, `.jpg`, `.jpeg`, `.svg` | IMAGE |
| `.doc`, `.docx`, `.md` | DOCUMENT |
| Others | OTHER |

## What Gets Registered

For each S3 object, the script creates a database record with:

- **File metadata**: filename, size, MIME type, upload date
- **S3 location**: `file_path` set to `s3://bucket/key`
- **Storage backend**: Set to `StorageBackend.S3`
- **Entity association**: Project or run ID extracted from path
- **File type**: Auto-detected from extension
- **Default settings**: `is_public=False`, `created_by="s3_bulk_import"`

## Error Handling

The script handles common issues:

- **Duplicate files**: Skips files already registered (based on S3 URI)
- **Access errors**: Reports permission or bucket access issues
- **Invalid patterns**: Falls back to default entity extraction
- **Database errors**: Rolls back failed registrations

## Monitoring Progress

The script provides progress updates every 100 files and a final summary:

```
Progress: 500 scanned, 450 registered, 30 skipped, 20 errors
==========================================
REGISTRATION SUMMARY
==========================================
Files scanned:    1000
Files registered: 850
Files skipped:    100  (already registered)
Errors:           50   (permission/validation issues)
```

## Best Practices

1. **Start with dry run**: Always test with `--dry-run` first
2. **Use specific prefixes**: Limit scope with `--prefix` to avoid scanning entire buckets
3. **Monitor logs**: Check for permission or pattern matching issues
4. **Backup database**: Consider backing up before large imports
5. **Run incrementally**: Process buckets/prefixes separately for better control

## Troubleshooting

### Common Issues

**"AWS credentials not found"**
- Configure AWS credentials using `aws configure` or environment variables

**"Access denied to bucket"**
- Verify your AWS credentials have the required S3 permissions
- Check bucket policies and IAM roles

**"No files registered"**
- Verify bucket name and prefix are correct
- Check entity patterns match your S3 structure
- Use `--dry-run` to see what would be processed

**"Database connection failed"**
- Ensure your database is running and accessible
- Check `SQLALCHEMY_DATABASE_URI` environment variable

### Getting Help

Run the script with `--help` for detailed usage information:
```bash
python scripts/register_s3_files.py --help