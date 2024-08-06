# Prepare

```
pip install -r requirements.txt
flask db init
flask db migrate -m "Initial migration."
flask db upgrade
```

# Run

```
python app.py
```

# Access

http://127.0.0.1:5000/graphql

Input the following:

```json
{
  getMetrics {
    name
    value
    timestamp
  }
  getTracing {
    traceId
    span
    duration
    timestamp
  }
  getLogs {
    message
    level
    timestamp
  }
}
```
