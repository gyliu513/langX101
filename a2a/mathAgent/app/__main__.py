#!/usr/bin/env python3
"""
Math Agent - A2A MCP Integration
Mathematical calculations, equation solving, calculus, statistics, and matrix operations
"""

import logging
import os
import sys

import click
import httpx
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryPushNotifier, InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from dotenv import load_dotenv

from app.agent import MathAgent
from app.agent_executor import MathAgentExecutor


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""


@click.command()
@click.option('--host', 'host', default='localhost')
@click.option('--port', 'port', default=8003)
def main(host, port):
    """Starts the Math Agent server."""
    try:
        if os.getenv('model_source',"google") == "google":
           if not os.getenv('GOOGLE_API_KEY'):
               raise MissingAPIKeyError(
                   'GOOGLE_API_KEY environment variable not set.'
               )
        else:
            if not os.getenv('TOOL_LLM_URL'):
                raise MissingAPIKeyError(
                    'TOOL_LLM_URL environment variable not set.'
                )
            if not os.getenv('TOOL_LLM_NAME'):
                raise MissingAPIKeyError(
                    'TOOL_LLM_NAME environment not variable not set.'
                )
    
        capabilities = AgentCapabilities(streaming=True, pushNotifications=True)
        
        # Math skills with comprehensive tags for better orchestrator routing
        math_skills = [
            AgentSkill(
                id="arithmetic_calculation",
                name="Arithmetic Calculation",
                description="Perform basic and advanced arithmetic calculations",
                tags=["math", "calculation", "arithmetic", "compute", "calculate", "add", "subtract", "multiply", "divide", "power", "sqrt", "sin", "cos", "tan", "log", "exp", "what is", "plus", "minus", "times", "+", "-", "*", "/", "^", "sum", "product", "number", "numbers"],
                examples=["Calculate 2 + 2", "What is sin(pi/4)?", "Compute sqrt(16)"]
            ),
            AgentSkill(
                id="equation_solving",
                name="Equation Solving",
                description="Solve algebraic equations and systems of equations",
                tags=["equation", "solve", "algebra", "polynomial", "quadratic", "linear", "system", "roots", "solutions"],
                examples=["Solve x^2 - 4 = 0", "Find roots of 2x + 5 = 11"]
            ),
            AgentSkill(
                id="calculus_operations",
                name="Calculus Operations", 
                description="Calculate derivatives and integrals of mathematical functions",
                tags=["calculus", "derivative", "integral", "differentiate", "integrate", "limit", "function", "dx", "dy"],
                examples=["Find derivative of x^2 + 3x + 2", "Integrate x^2 dx"]
            ),
            AgentSkill(
                id="matrix_operations",
                name="Matrix Operations",
                description="Perform matrix calculations including multiplication, inversion, determinant",
                tags=["matrix", "linear", "algebra", "determinant", "inverse", "transpose", "multiply", "eigenvalue", "vector"],
                examples=["Determinant of [[1,2],[3,4]]", "Multiply matrices"]
            ),
            AgentSkill(
                id="statistics_analysis",
                name="Statistics Analysis",
                description="Calculate statistical measures and analyze data sets",
                tags=["statistics", "stats", "mean", "median", "mode", "standard", "deviation", "variance", "data", "analysis"],
                examples=["Mean of [1,2,3,4,5]", "Standard deviation of data"]
            )
        ]
        
        agent_card = AgentCard(
            name='Math Agent',
            description='Advanced mathematical assistant for calculations, equation solving, calculus, statistics, and matrix operations via MCP',
            url=f'http://{host}:{port}/',
            version='1.0.0',
            defaultInputModes=MathAgent.SUPPORTED_CONTENT_TYPES,
            defaultOutputModes=MathAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=math_skills,
        )

        # Create request handler with math agent executor
        httpx_client = httpx.AsyncClient()
        request_handler = DefaultRequestHandler(
            agent_executor=MathAgentExecutor(),
            task_store=InMemoryTaskStore(),
            push_notifier=InMemoryPushNotifier(httpx_client),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )

        print(f"🧮 Starting Math Agent on port {port}")
        print("📊 Available capabilities (via MCP):")
        print("  • Arithmetic calculations (2+2, sin(pi/4), sqrt(16))")
        print("  • Equation solving (x^2 - 4 = 0)")
        print("  • Calculus (derivatives and integrals)")
        print("  • Matrix operations (multiply, inverse, determinant)")
        print("  • Statistics (mean, median, std dev, etc.)")

        uvicorn.run(server.build(), host=host, port=port)

    except MissingAPIKeyError as e:
        logger.error(f'Error: {e}')
        sys.exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        sys.exit(1)


if __name__ == "__main__":
    main() 