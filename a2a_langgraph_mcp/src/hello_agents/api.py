import asyncio
import json
import logging
import uuid
from typing import Dict, Any, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from hello_agents.agents.hello_agent import HelloWorldAgent
from hello_agents.agents.orchestrator_agent import OrchestratorAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(title="A2A LangGraph MCP Demo")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agents
hello_agent = HelloWorldAgent()
orchestrator_agent = OrchestratorAgent()


class QueryRequest(BaseModel):
    """Request model for agent queries."""
    query: str
    context_id: str = None


class QueryResponse(BaseModel):
    """Response model for agent queries."""
    content: Any
    is_task_complete: bool = False
    require_user_input: bool = False


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "A2A LangGraph MCP Demo API"}


@app.post("/api/hello")
async def hello_endpoint(request: QueryRequest):
    """Hello agent endpoint."""
    context_id = request.context_id or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    
    # Process the request with the hello agent
    response = None
    async for chunk in hello_agent.stream(request.query, context_id, task_id):
        response = chunk
    
    return QueryResponse(**response)


@app.post("/api/orchestrator")
async def orchestrator_endpoint(request: QueryRequest):
    """Orchestrator agent endpoint."""
    context_id = request.context_id or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    
    # Process the request with the orchestrator agent
    response = None
    async for chunk in orchestrator_agent.stream(request.query, context_id, task_id):
        response = chunk
    
    return QueryResponse(**response)


@app.websocket("/ws/hello")
async def hello_websocket(websocket: WebSocket):
    """WebSocket endpoint for the hello agent."""
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            request = json.loads(data)
            
            # Extract query and context_id
            query = request.get("query", "")
            context_id = request.get("context_id", str(uuid.uuid4()))
            task_id = str(uuid.uuid4())
            
            # Process with hello agent and stream responses
            async for chunk in hello_agent.stream(query, context_id, task_id):
                await websocket.send_json(chunk)
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")


@app.websocket("/ws/orchestrator")
async def orchestrator_websocket(websocket: WebSocket):
    """WebSocket endpoint for the orchestrator agent."""
    await websocket.accept()
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            request = json.loads(data)
            
            # Extract query and context_id
            query = request.get("query", "")
            context_id = request.get("context_id", str(uuid.uuid4()))
            task_id = str(uuid.uuid4())
            
            # Process with orchestrator agent and stream responses
            async for chunk in orchestrator_agent.stream(query, context_id, task_id):
                await websocket.send_json(chunk)
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")


def start_server(host="0.0.0.0", port=8000):
    """Start the API server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()