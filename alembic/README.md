# Database Migrations with Alembic

This directory contains database migration scripts for the APIServer project. The migrations are managed using Alembic, which is an industry-standard migration tool for SQLAlchemy-based applications.

## Migration Structure

- `alembic.ini`: The main Alembic configuration file (in project root)
- `alembic/env.py`: Environment configuration for Alembic
- `alembic/versions/`: Directory containing all migration scripts
- `alembic/script.py.mako`: Template for new migration scripts

## How to Use Migrations

The following commands have been added to the project's Makefile:

### Apply Migrations

```bash
make migrate
```

This command runs all pending migrations to bring your database up to date with the latest schema.

### Create a New Migration

Automatically generate a migration based on model changes:

```bash
make migrate-new message="Description of changes"
```

Create an empty migration file:

```bash
make migrate-empty message="Description of changes"
```

### Rollback Migrations

Roll back the most recent migration:

```bash
make migrate-rollback
```

### Check Current Status

See which migration version is currently applied:

```bash
make migrate-current
```

## Testing the Migration

To test the initial migration:

1. Ensure your database connection settings are correctly set in `.env` or environment variables:
   - `DB_SERVER`
   - `DB_PORT`
   - `DB_PASSWORD`
   - `DB_USER`
   - `DB_NAME`

2. Run the migration:
   ```bash
   make migrate
   ```

3. Verify the tables were created with the expected schema, particularly that the Project table has a `name` field with a maximum length of 2048 characters.

## Troubleshooting

If you encounter issues during migration:

1. Check your database connection settings
2. Review the alembic.ini file to ensure the SQLAlchemy URL is correctly set
3. Ensure you have the necessary permissions to create/alter tables in the database
4. Check the migration logs for specific error messages

## Creating New Models/Tables

When creating new models:

1. Define the model in the appropriate file using SQLModel
2. Import the model in `alembic/env.py` to ensure it's detected during autogeneration
3. Generate a new migration using `make migrate-new message="Add new model"`
4. Review the generated migration file for accuracy
5. Apply the migration using `make migrate`

## Additional Resources

- [Alembic Documentation](https://alembic.sqlalchemy.org/en/latest/)
- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)