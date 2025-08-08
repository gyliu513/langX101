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
cd postgres/docker-compose
docker-compose up -d
```

This will start PostgreSQL in detached mode.

### Stopping the PostgreSQL Container

```bash
docker-compose down
```

To remove the volumes as well (this will delete all data):

```bash
docker-compose down -v
```

### Connecting to PostgreSQL

From your host machine:

```bash
psql -h localhost -p 5432 -U postgres -d postgres
```

You will be prompted for the password specified in the `.env` file.

From another Docker container (if they share the same network):

```
Host: postgres_db
Port: 5432
User: postgres
Password: (from .env file)
Database: postgres
```

## Data Persistence

Data is stored in a Docker volume named `postgres_data`. This ensures that your data persists even if the container is removed.

## Database Initialization

If you want to initialize the database with scripts, uncomment the volume mount in `docker-compose.yml` and add your SQL scripts to the `init-scripts` directory.

## Security Note

Remember to change the default password in the `.env` file before using this in any production environment.