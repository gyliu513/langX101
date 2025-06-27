import os
import asyncio
from collections.abc import AsyncIterable
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

memory = MemorySaver()

class ResponseFormat(BaseModel):
    """Response format for the Instana agent."""
    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str

class InstanaAgent:
    """
    InstanaAgent - a specialized assistant for Instana monitoring via MCP HTTP.
    
    This agent connects to Instana via the MCP HTTP protocol and provides
    natural language interface to Instana monitoring operations.
    """
    SYSTEM_INSTRUCTION = (
        'You are a specialized assistant for Instana monitoring and observability. '
        'Your sole purpose is to use the Instana MCP tools to help users monitor their applications and infrastructure. '
        'You can retrieve events, alerts, application metrics, infrastructure resources, and more from Instana. '
        'If the user asks about anything other than Instana monitoring, '
        'politely state that you cannot help with that topic and can only assist with Instana-related queries. '
        'Do not attempt to answer unrelated questions or use tools for other purposes. '
        'Set response status to input_required if the user needs to provide more information. '
        'Set response status to error if there is an error while processing the request. '
        'Set response status to completed if the request is complete. '
        'Always provide clear, concise responses about the Instana operations you perform.'
    )

    def __init__(self):
        self.model = ChatGoogleGenerativeAI(model='gemini-2.0-flash')
        # Set Instana environment variables
        os.environ["INSTANA_BASE_URL"] = os.getenv("INSTANA_BASE_URL", "")
        os.environ["INSTANA_API_TOKEN"] = os.getenv("INSTANA_API_TOKEN", "")
        self.tools = []
        self.mcp_session = None
        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=ResponseFormat,
        )

    async def _init_mcp_tools(self):
        """Initialize MCP tools using HTTP connection to Instana MCP server."""
        if self.tools:
            return self.tools
            
        # Set environment variables
        base_url = os.getenv("INSTANA_BASE_URL", "")
        api_token = os.getenv("INSTANA_API_TOKEN", "")
        
        if not base_url or not api_token:
            raise RuntimeError("INSTANA_BASE_URL and INSTANA_API_TOKEN environment variables must be set")
        
        # MCP server endpoint - default to localhost:8000/mcp
        mcp_server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
        
        try:
            # Use HTTP connection to MCP server
            async with asyncio.timeout(15):
                async with streamablehttp_client(mcp_server_url) as (read_stream, write_stream, _):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        tools = await load_mcp_tools(session)
                        print(f"Successfully initialized Instana MCP HTTP connection with {len(tools)} tools")
                        return tools
                    
        except Exception as e:
            print(f"Instana MCP HTTP connection failed: {str(e)}")
            raise RuntimeError(f"Failed to initialize Instana MCP tools: {str(e)}")

    def invoke(self, query, context_id) -> dict:
        """
        Invoke the agent with a query.
        
        Args:
            query: The user's query string
            context_id: A unique identifier for the conversation context
            
        Returns:
            The agent's response as a dictionary
        """
        # For non-async usage, return a simulated response
        return {
            'is_task_complete': True,
            'require_user_input': False,
            'content': (
                "I'm the Instana monitoring agent. To use my full capabilities with MCP, "
                "please use the async methods or run me in an async context. "
                f"Your query was: '{query}'"
            ),
        }

    async def ainvoke(self, query, context_id) -> dict:
        """
        Asynchronously invoke the agent with a query.
        
        Args:
            query: The user's query string
            context_id: A unique identifier for the conversation context
            
        Returns:
            The agent's response as a dictionary
        """
        if not self.tools:
            try:
                self.tools = await self._init_mcp_tools()
                self.graph = create_react_agent(
                    self.model,
                    tools=self.tools,
                    checkpointer=memory,
                    prompt=self.SYSTEM_INSTRUCTION,
                    response_format=ResponseFormat,
                )
            except Exception as e:
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': f"Error initializing Instana MCP tools: {str(e)}",
                }
        config = {'configurable': {'thread_id': context_id}}
        self.graph.invoke({'messages': [('user', query)]}, config)
        return self.get_agent_response(config)

    async def stream(self, query, context_id) -> AsyncIterable[dict[str, Any]]:
        """
        Stream the agent's response.
        
        Args:
            query: The user's query string
            context_id: A unique identifier for the conversation context
            
        Yields:
            Dictionaries containing the streaming response state
        """
        if not self.tools:
            yield {'is_task_complete': False, 'require_user_input': False, 'content': 'Initializing Instana monitoring tools...'}
            try:
                self.tools = await self._init_mcp_tools()
                self.graph = create_react_agent(
                    self.model,
                    tools=self.tools,
                    checkpointer=memory,
                    prompt=self.SYSTEM_INSTRUCTION,
                    response_format=ResponseFormat,
                )
            except Exception as e:
                yield {'is_task_complete': False, 'require_user_input': True, 'content': f"Error initializing Instana MCP tools: {str(e)}"}
                return

        inputs = {'messages': [('user', query)]}
        config = {'configurable': {'thread_id': context_id}}
        for item in self.graph.stream(inputs, config, stream_mode='values'):
            message = item['messages'][-1]
            if isinstance(message, AIMessage) and message.tool_calls:
                yield {'is_task_complete': False, 'require_user_input': False, 'content': 'Looking up Instana monitoring information...'}
            elif isinstance(message, ToolMessage):
                yield {'is_task_complete': False, 'require_user_input': False, 'content': 'Processing Instana tool response...'}
        yield self.get_agent_response(config)
    
    async def __del__(self):
        """Clean up resources when the agent is destroyed."""
        await self.cleanup()
        
    async def cleanup(self):
        """Explicitly clean up resources when done with the agent."""
        # Reset the session and process references
        self.mcp_session = None
        self.tools = []
        if hasattr(self, '_tools_loaded'):
            delattr(self, '_tools_loaded')
            
    async def check_instana_server(self) -> tuple[bool, str]:
        """
        Check if the Instana server is accessible.
        
        Returns:
            A tuple of (is_accessible, message)
        """
        import httpx
        
        base_url = os.getenv("INSTANA_BASE_URL", "")
        api_token = os.getenv("INSTANA_API_TOKEN", "")
        
        if not api_token:
            return False, "Instana API token is not configured"
            
        if not base_url:
            return False, "Instana base URL is not configured"
            
        # Remove trailing slash if present
        if base_url.endswith('/'):
            base_url = base_url[:-1]
            
        # Try to access the Instana API health endpoint
        try:
            headers = {
                "Authorization": f"apiToken {api_token}",
                "Content-Type": "application/json"
            }
            
            # Create a client that ignores SSL verification
            async with httpx.AsyncClient(verify=False, timeout=10.0) as client:
                # Try the health endpoint first
                response = await client.get(f"{base_url}/api/instana/health", headers=headers)
                if response.status_code == 200:
                    return True, "Instana server is accessible"
                else:
                    return False, f"Instana server returned status {response.status_code}"
                        
        except httpx.TimeoutException:
            return False, "Timeout connecting to Instana server"
        except httpx.RequestError as e:
            return False, f"Connection error: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    async def check_mcp_server(self) -> tuple[bool, str]:
        """
        Check if the MCP server is accessible.
        
        Returns:
            A tuple of (is_accessible, message)
        """
        import httpx
        
        mcp_server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8000/mcp")
        
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Try to access the MCP server endpoint
                response = await client.get(mcp_server_url.replace('/mcp', '/health'))
                if response.status_code == 200:
                    return True, f"MCP server is accessible at {mcp_server_url}"
                else:
                    return False, f"MCP server returned status {response.status_code}"
                        
        except httpx.TimeoutException:
            return False, f"Timeout connecting to MCP server at {mcp_server_url}"
        except httpx.RequestError as e:
            return False, f"Connection error to MCP server: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error checking MCP server: {str(e)}"
        
    def get_agent_response(self, config):
        """
        Get the formatted agent response from the current state.
        
        Args:
            config: The configuration dictionary with thread_id
            
        Returns:
            A dictionary containing the response state and content
        """
        current_state = self.graph.get_state(config)
        structured_response = current_state.values.get('structured_response')
        if structured_response and isinstance(
            structured_response, ResponseFormat
        ):
            if structured_response.status == 'input_required':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            if structured_response.status == 'error':
                return {
                    'is_task_complete': False,
                    'require_user_input': True,
                    'content': structured_response.message,
                }
            if structured_response.status == 'completed':
                return {
                    'is_task_complete': True,
                    'require_user_input': False,
                    'content': structured_response.message,
                }

        return {
            'is_task_complete': False,
            'require_user_input': True,
            'content': (
                'We are unable to process your request at the moment. '
                'Please try again.'
            ),
        }

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']