import argparse
import asyncio
import logging
import multiprocessing
import os
import sys
import time

from hello_agents.api import start_server
from hello_agents.mcp.server import serve as start_mcp_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def run_mcp_server(host, port):
    """Run the MCP server in a separate process."""
    logger.info(f"Starting MCP server at {host}:{port}")
    start_mcp_server(host=host, port=port)


def run_api_server(host, port):
    """Run the API server in a separate process."""
    logger.info(f"Starting API server at {host}:{port}")
    start_server(host=host, port=port)


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(description="A2A LangGraph MCP Demo")
    parser.add_argument("--mcp-host", default="localhost", help="MCP server host")
    parser.add_argument("--mcp-port", type=int, default=10000, help="MCP server port")
    parser.add_argument("--api-host", default="0.0.0.0", help="API server host")
    parser.add_argument("--api-port", type=int, default=8000, help="API server port")
    parser.add_argument("--mcp-only", action="store_true", help="Run only the MCP server")
    parser.add_argument("--api-only", action="store_true", help="Run only the API server")
    
    args = parser.parse_args()
    
    # Check if Google API key is set
    if not os.environ.get("GOOGLE_API_KEY"):
        logger.error("GOOGLE_API_KEY environment variable is not set")
        sys.exit(1)
    
    processes = []
    
    try:
        # Start MCP server if requested
        if not args.api_only:
            mcp_process = multiprocessing.Process(
                target=run_mcp_server,
                args=(args.mcp_host, args.mcp_port)
            )
            mcp_process.start()
            processes.append(mcp_process)
            logger.info(f"MCP server started with PID {mcp_process.pid}")
            
            # Give MCP server time to start
            time.sleep(2)
        
        # Start API server if requested
        if not args.mcp_only:
            api_process = multiprocessing.Process(
                target=run_api_server,
                args=(args.api_host, args.api_port)
            )
            api_process.start()
            processes.append(api_process)
            logger.info(f"API server started with PID {api_process.pid}")
        
        # Wait for processes to complete
        for process in processes:
            process.join()
            
    except KeyboardInterrupt:
        logger.info("Shutting down servers...")
        for process in processes:
            process.terminate()
            process.join()
        logger.info("Servers shut down")


if __name__ == "__main__":
    main()