# PostgreSQL Docker Compose Setup

This directory contains a Docker Compose configuration for running PostgreSQL in a container.

## Prerequisites

- Docker and Docker Compose installed on your system
- Basic understanding of PostgreSQL

## Configuration

The setup uses environment variables stored in the `.env` file:

- `POSTGRES_USER`: Database user (default: postgres)
- `POSTGRES_PASSWORD`: Database password (default: your_secure_password)
- `POSTGRES_DB`: Database name (default: postgres)
- `POSTGRES_PORT`: Port to expose PostgreSQL (default: 5432)

## Usage

### Starting the PostgreSQL Container

```bash
cd postgres
docker compose up -d
```

This will start PostgreSQL in detached mode.

### Stopping the PostgreSQL Container

```bash
docker compose down
```

To remove the volumes as well (this will delete all data):

```bash
docker compose down -v
```

### Connecting to PostgreSQL

From your host machine:

```bash
# Method 1: Set password as environment variable (recommended)
PGPASSWORD=postgres psql -h localhost -p 5432 -U postgres -d postgres

# Method 2: Type password when prompted
psql -h localhost -p 5432 -U postgres -d postgres
# Then enter: postgres
```

From another Docker container (if they share the same network):

```
Host: postgres_db
Port: 5432
User: postgres
Password: (from .env file)
Database: postgres
```

## Database Operations

### Basic Connection Commands

```bash
# Connect to database
PGPASSWORD=postgres psql -h localhost -p 5432 -U postgres -d postgres

# List all databases
\l

# Connect to a specific database
\c database_name

# List all tables in current database
\dt

# Describe a table structure
\d table_name

# List all schemas
\dn

# Exit psql
\q
```

### Query Operations

```bash
# Basic SELECT query
SELECT * FROM sample_table;

# SELECT with WHERE clause
SELECT * FROM sample_table WHERE name = 'Sample 1';

# SELECT specific columns
SELECT id, name FROM sample_table;

# SELECT with ORDER BY
SELECT * FROM sample_table ORDER BY created_at DESC;

# SELECT with LIMIT
SELECT * FROM sample_table LIMIT 5;

# SELECT with LIKE (pattern matching)
SELECT * FROM sample_table WHERE name LIKE '%Sample%';

# COUNT records
SELECT COUNT(*) FROM sample_table;

# GROUP BY with aggregation
SELECT name, COUNT(*) FROM sample_table GROUP BY name;
```

### Insert Operations

```bash
# Insert a single record
INSERT INTO sample_table (name, description) VALUES ('New Sample', 'This is a new sample record');

# Insert multiple records
INSERT INTO sample_table (name, description) VALUES 
    ('Sample 4', 'Fourth sample record'),
    ('Sample 5', 'Fifth sample record'),
    ('Sample 6', 'Sixth sample record');

# Insert with RETURNING (get the inserted data)
INSERT INTO sample_table (name, description) 
VALUES ('Returning Sample', 'This will return the inserted data')
RETURNING id, name, description;
```

### Update Operations

```bash
# Update all records matching a condition
UPDATE sample_table 
SET description = 'Updated description' 
WHERE name = 'Sample 1';

# Update multiple columns
UPDATE sample_table 
SET name = 'Updated Name', description = 'Updated description' 
WHERE id = 1;

# Update with RETURNING (get the updated data)
UPDATE sample_table 
SET description = 'Updated with returning'
WHERE id = 1
RETURNING id, name, description;

# Update with subquery
UPDATE sample_table 
SET description = 'Bulk updated'
WHERE id IN (SELECT id FROM sample_table WHERE name LIKE '%Sample%');
```

### Delete Operations

```bash
# Delete specific records
DELETE FROM sample_table WHERE name = 'Sample 1';

# Delete with condition
DELETE FROM sample_table WHERE id > 5;

# Delete with RETURNING (get the deleted data)
DELETE FROM sample_table 
WHERE id = 1
RETURNING id, name, description;

# Delete all records (be careful!)
DELETE FROM sample_table;

# Truncate table (faster than DELETE, resets sequences)
TRUNCATE TABLE sample_table;
```

### Advanced Queries

```bash
# JOIN example (if you have multiple tables)
SELECT t1.name, t2.description 
FROM table1 t1 
JOIN table2 t2 ON t1.id = t2.table1_id;

# Subquery example
SELECT * FROM sample_table 
WHERE id IN (SELECT id FROM sample_table WHERE name LIKE '%Sample%');

# Window functions
SELECT name, description, 
       ROW_NUMBER() OVER (ORDER BY created_at) as row_num
FROM sample_table;

# Conditional queries with CASE
SELECT name, description,
       CASE 
           WHEN id < 3 THEN 'Early'
           WHEN id < 6 THEN 'Middle'
           ELSE 'Late'
       END as category
FROM sample_table;
```

### Transaction Operations

```bash
# Start a transaction
BEGIN;

# Perform operations
INSERT INTO sample_table (name, description) VALUES ('Transaction Test', 'Testing transactions');
UPDATE sample_table SET description = 'Updated in transaction' WHERE id = 1;

# Commit the transaction
COMMIT;

# Or rollback if something goes wrong
ROLLBACK;
```

### Database Management

```bash
# Create a new database
CREATE DATABASE new_database;

# Create a new user
CREATE USER new_user WITH PASSWORD 'new_password';

# Grant permissions
GRANT ALL PRIVILEGES ON DATABASE new_database TO new_user;

# Create a new table
CREATE TABLE new_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

# Create an index
CREATE INDEX idx_sample_table_name ON sample_table(name);

# View table statistics
SELECT schemaname, tablename, attname, n_distinct, correlation 
FROM pg_stats 
WHERE tablename = 'sample_table';
```

### Export/Import Operations

```bash
# Export table to CSV
\copy sample_table TO '/tmp/sample_table.csv' CSV HEADER;

# Import CSV to table
\copy sample_table FROM '/tmp/sample_table.csv' CSV HEADER;

# Export entire database
pg_dump -h localhost -p 5432 -U postgres -d postgres > backup.sql

# Import database from dump
psql -h localhost -p 5432 -U postgres -d postgres < backup.sql
```

## Data Persistence

Data is stored in a Docker volume named `postgres_data`. This ensures that your data persists even if the container is removed.

## Database Initialization

The database is automatically initialized with a sample table and data from the `init-scripts/01-init.sql` file. This script creates:

- A `sample_table` with sample data
- A `sample_user` with limited permissions

## Security Note

Remember to change the default password in the `.env` file before using this in any production environment.