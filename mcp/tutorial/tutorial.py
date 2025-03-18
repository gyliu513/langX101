# server.py
from mcp.server.fastmcp import FastMCP, Image, Context
from PIL import Image as PILImage

# Create an MCP server
mcp = FastMCP("Demo")

@mcp.tool()
async def long_task(files: list[str], ctx: Context) -> str:
    """Process multiple files with progress tracking"""
    for i, file in enumerate(files):
        ctx.info(f"Processing {file}")
        await ctx.report_progress(i, len(files))
        data, mime_type = await ctx.read_resource(f"file://{file}")
    return "Processing complete"

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

# Add a dynamic greeting resource
@mcp.resource("greeting2://{name}")
def get_greeting2(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}2!"

@mcp.resource("config://app")
def get_config() -> str:
    """Static configuration data"""
    return "App configuration here"


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Dynamic user data"""
    return f"Profile data for user {user_id}"


@mcp.prompt()
def review_code(code: str) -> str:
    return f"Please review this code:\n\n{code}"

@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    return Image(data=img.tobytes(), format="png")

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
def query_instana_events2(params=None):
    return "aaaa"

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


if __name__ == "__main__":
    mcp.run()