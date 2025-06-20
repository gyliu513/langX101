#!/usr/bin/env python3
"""
Math Agent using MCP (Model Context Protocol) Server
"""
import asyncio
import os
import sys
from pathlib import Path
from typing import List

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

class MathAgent:
    """Math Agent using MCP server for mathematical operations"""
    
    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']
    
    def __init__(self):
        self.agent = None
        self._initialize_model()
    
    def _initialize_model(self):
        """Initialize the Google AI model"""
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("⚠️  GOOGLE_API_KEY not set. Using default configuration.")
            # Use default configuration without explicit API key
            # The ChatGoogleGenerativeAI will try to find the key from other sources
            self.model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                temperature=0
            )
        else:
            self.model = ChatGoogleGenerativeAI(
                model="gemini-1.5-flash",
                google_api_key=api_key,
                temperature=0
            )
    
    async def _create_agent_with_mcp_tools(self):
        """Create agent with MCP tools loaded from math server"""
        # Get the path to the math MCP server
        current_dir = Path(__file__).parent.parent
        math_server_path = current_dir / "math_mcp_server.py"
        
        server_params = StdioServerParameters(
            command="python",
            args=[str(math_server_path)],
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Load MCP tools
                tools = await load_mcp_tools(session)
                print(f"✅ Loaded {len(tools)} MCP tools:")
                for tool in tools:
                    print(f"  - {tool.name}: {tool.description}")
                
                # Create agent with MCP tools
                self.agent = create_react_agent(self.model, tools)
                return session  # Return session to keep it alive
    
    async def process_request(self, request: str) -> str:
        """Process a mathematical request using MCP tools"""
        try:
            # Create agent with MCP tools for each request
            # This ensures fresh connection each time
            current_dir = Path(__file__).parent.parent
            math_server_path = current_dir / "math_mcp_server.py"
            
            server_params = StdioServerParameters(
                command="python",
                args=[str(math_server_path)],
            )
            
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    
                    # Load MCP tools
                    tools = await load_mcp_tools(session)
                    
                    # Create agent with MCP tools
                    agent = create_react_agent(self.model, tools)
                    
                    # Process the request
                    response = await agent.ainvoke({"messages": request})
                    
                    # Extract the final message content
                    if "messages" in response:
                        messages = response["messages"]
                        if messages and hasattr(messages[-1], 'content'):
                            return messages[-1].content
                        elif messages:
                            return str(messages[-1])
                    
                    return str(response)
                    
        except Exception as e:
            return f"❌ Error processing mathematical request: {str(e)}"
    
    def get_capabilities(self) -> List[str]:
        """Return list of mathematical capabilities"""
        return [
            "Arithmetic calculations and expression evaluation",
            "Algebraic equation solving",
            "Calculus operations (derivatives and integrals)",
            "Matrix operations and linear algebra",
            "Statistical analysis and data processing",
            "Mathematical function plotting and visualization"
        ]

# Global agent instance
math_agent = MathAgent()

async def process_math_request(request: str) -> str:
    """Process a mathematical request"""
    return await math_agent.process_request(request)

def get_math_capabilities() -> List[str]:
    """Get mathematical capabilities"""
    return math_agent.get_capabilities()

# Test function
async def test_agent():
    """Test the math agent"""
    test_requests = [
        "What is (3 + 5) × 12?",
        "Solve the equation 2x + 5 = 15",
        "Calculate the derivative of x^2 + 3x + 2",
        "Find the mean of [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]"
    ]
    
    for request in test_requests:
        print(f"\n🔢 Request: {request}")
        response = await process_math_request(request)
        print(f"📊 Response: {response}")

if __name__ == "__main__":
    asyncio.run(test_agent()) 