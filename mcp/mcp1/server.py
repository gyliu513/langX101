# server.py
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo")

# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b

# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"

import os
import sys
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def convert_to_epoch_milliseconds(date_str):
    """Convert a date string in format 'MM/DD/YYYY' to Unix epoch time in milliseconds."""
    dt = datetime.strptime(date_str, "%m/%d/%Y")
    return int(dt.timestamp() * 1000)

@mcp.tool()
def query_instana_events(params=None):
    
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

    """Query Instana API for events."""
    url = f"{INSTANA_URL}/api/events"
    start_time = convert_to_epoch_milliseconds("01/15/2025")
    end_time = convert_to_epoch_milliseconds("01/16/2025")

    # Optional query parameters
    params = {
        "from": start_time,
        "to": end_time,
        "eventTypeFilters": "CHANGE"
    }
    
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        response.raise_for_status()  # Raise an exception for HTTP errors
        return response.json()[0]
    except requests.exceptions.HTTPError as err:
        print(f"HTTP Error: {err}")
    except requests.exceptions.RequestException as err:
        print(f"Error: {err}")
    return None
