import json
import logging
from typing import Dict, Any, Optional

import httpx

logger = logging.getLogger(__name__)


class MCPClient:
    """Simple MCP client implementation."""
    
    def __init__(self, host="localhost", port=10000):
        self.base_url = f"http://{host}:{port}"
        logger.info(f"Initialized MCP client with base URL: {self.base_url}")
    
    async def list_tools(self) -> Dict[str, Any]:
        """List all available tools from the MCP server."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/tools")
            response.raise_for_status()
            return response.json()
    
    async def list_resources(self) -> Dict[str, Any]:
        """List all available resources from the MCP server."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/resources")
            response.raise_for_status()
            return response.json()
    
    async def get_resource(self, resource_id: str) -> Dict[str, Any]:
        """Get a specific resource from the MCP server."""
        # Extract the resource name from the resource URI if needed
        if resource_id.startswith("resource://"):
            resource_name = resource_id.split("resource://")[1]
        else:
            resource_name = resource_id
            
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/resources/{resource_name}")
            response.raise_for_status()
            return response.json()
    
    async def find_agent(self, query: str) -> Dict[str, Any]:
        """Find an agent that can handle the given query."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/find_agent",
                json={"query": query}
            )
            response.raise_for_status()
            return response.json()


# Singleton instance for easy access
_client_instance: Optional[MCPClient] = None


def get_client(host="localhost", port=10000) -> MCPClient:
    """Get or create a singleton MCPClient instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = MCPClient(host=host, port=port)
    return _client_instance