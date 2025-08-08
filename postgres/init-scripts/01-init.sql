-- Create a sample table
CREATE TABLE IF NOT EXISTS sample_table (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Insert some sample data
INSERT INTO sample_table (name, description) VALUES
    ('Sample 1', 'This is the first sample record'),
    ('Sample 2', 'This is the second sample record'),
    ('Sample 3', 'This is the third sample record');

-- Create a sample user with limited permissions
CREATE USER sample_user WITH PASSWORD 'sample_password';
GRANT CONNECT ON DATABASE postgres TO sample_user;
GRANT USAGE ON SCHEMA public TO sample_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON sample_table TO sample_user;
GRANT USAGE, SELECT ON SEQUENCE sample_table_id_seq TO sample_user;

-- You can add more initialization commands here
