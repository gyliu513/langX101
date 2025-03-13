import os
import sys
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants
INSTANA_URL = os.getenv('INSTANA_URL')
API_TOKEN = os.getenv('API_TOKEN')

if not INSTANA_URL or not API_TOKEN:
    print("Error: INSTANA_URL and API_TOKEN must be set in the .env file.")
    sys.exit(1)

# Headers for Instana API
HEADERS = {
    "Authorization": f"apiToken {API_TOKEN}",
    "Content-Type": "application/json"
}

def convert_to_epoch_milliseconds(date_str):
    """Convert a date string in format 'MM/DD/YYYY' to Unix epoch time in milliseconds."""
    dt = datetime.strptime(date_str, "%m/%d/%Y")
    return int(dt.timestamp() * 1000)

def query_instana_events(params=None):
    """Query Instana API for events."""
    url = f"{INSTANA_URL}/api/events"
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()[0]
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}")
    except requests.exceptions.RequestException as err:
        print(f"Error: {err}")
    return None

def main():
    # Define the time range in Unix epoch milliseconds
    start_time = convert_to_epoch_milliseconds("01/15/2025")
    end_time = convert_to_epoch_milliseconds("01/15/2025")

    # Optional query parameters
    params = {
        "from": start_time,
        "to": end_time,
        "eventTypeFilters": "CHANGE"
    }

    # Query the Instana API for events
    events = query_instana_events(params=params)

    if events:
        print(json.dumps(events, indent=2))

if __name__ == "__main__":
    main()
