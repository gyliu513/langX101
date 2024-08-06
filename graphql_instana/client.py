import requests

def query_all_users():
    url = 'http://127.0.0.1:5000/graphql'
    query = """
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
    """
    response = requests.post(url, json={'query': query})
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Query failed to run with a {response.status_code}.")

def main():
    try:
        result = query_all_users()
        print("Query result:")
        print(result)
    except Exception as e:
        print(e)

if __name__ == '__main__':
    main()
