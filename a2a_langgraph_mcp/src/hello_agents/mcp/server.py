import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

logger = logging.getLogger(__name__)

# Directory where agent cards are stored
AGENT_CARDS_DIR = 'agent_cards'


class Tool(BaseModel):
    """Tool representation for MCP."""
    name: str
    description: str
    parameters: dict


class MCPServer:
    """Simple MCP server implementation."""
    
    def __init__(self, host="localhost", port=10000):
        self.host = host
        self.port = port
        self.app = FastAPI(title="Simple MCP Server")
        self.tools = []
        self.agent_cards = {}
        
        # Configure CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # Register routes
        self.setup_routes()
        
    def setup_routes(self):
        """Set up the API routes."""
        
        @self.app.get("/")
        async def root():
            return {"message": "Hello from MCP Server"}
        
        @self.app.get("/tools")
        async def list_tools():
            return {"tools": self.tools}
        
        @self.app.get("/resources")
        async def list_resources():
            return {"resources": list(self.agent_cards.keys())}
        
        @self.app.get("/resources/{resource_id}")
        async def get_resource(resource_id: str):
            if resource_id not in self.agent_cards:
                raise HTTPException(status_code=404, detail="Resource not found")
            return {"resource": self.agent_cards[resource_id]}
        
        @self.app.post("/find_agent")
        async def find_agent(query: dict):
            """Find the most relevant agent for a given query."""
            if not self.agent_cards:
                raise HTTPException(status_code=404, detail="No agents available")
            
            # In a real implementation, this would use embeddings and similarity search
            # For simplicity, we'll just return the first agent
            first_agent_id = list(self.agent_cards.keys())[0]
            return self.agent_cards[first_agent_id]
    
    def register_tool(self, tool: Tool):
        """Register a tool with the MCP server."""
        self.tools.append(tool)
        logger.info(f"Registered tool: {tool.name}")
    
    def load_agent_cards(self):
        """Load agent cards from the specified directory."""
        dir_path = Path(AGENT_CARDS_DIR)
        if not dir_path.exists():
            logger.warning(f"Agent cards directory not found: {AGENT_CARDS_DIR}")
            os.makedirs(dir_path, exist_ok=True)
            return
        
        for file_path in dir_path.glob("*.json"):
            try:
                with open(file_path, "r") as f:
                    agent_card = json.load(f)
                    resource_id = f"resource://{file_path.stem}"
                    self.agent_cards[resource_id] = agent_card
                    logger.info(f"Loaded agent card: {resource_id}")
            except Exception as e:
                logger.error(f"Error loading agent card {file_path}: {e}")
    
    def run(self):
        """Run the MCP server."""
        self.load_agent_cards()
        logger.info(f"Starting MCP server at {self.host}:{self.port}")
        uvicorn.run(self.app, host=self.host, port=self.port)


def create_hello_tool():
    """Create a simple hello world tool."""
    return Tool(
        name="hello_world",
        description="A simple tool that returns a hello world message",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name to greet"
                }
            },
            "required": ["name"]
        }
    )


def serve(host="localhost", port=10000):
    """Start the MCP server."""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create and configure the server
    server = MCPServer(host=host, port=port)
    
    # Register tools
    server.register_tool(create_hello_tool())
    
    # Run the server
    server.run()


if __name__ == "__main__":
    serve()