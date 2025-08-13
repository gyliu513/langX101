## Drizzle Demo — Setup and Usage

### 1. Start the database
```bash
docker compose up -d
```

### 2. Generate migration files
```bash
npm run db:generate
```

### 3. Apply migrations
```bash
npm run db:migrate
```

### 4. Optional: Push schema directly to the database (skip SQL generation)
```bash
npm run db:push
```

### 5. Insert seed data
```bash
npm run db:seed
```

### 6. Run the CRUD test
```bash
npm run dev
```

### 7. Visual management
```bash
npm run db:studio
```

Or visit Adminer: [http://localhost:8080](http://localhost:8080)

Login details:
- **System**: PostgreSQL
- **Server**: db
- **User**: postgres
- **Password**: postgres
- **Database**: demo


