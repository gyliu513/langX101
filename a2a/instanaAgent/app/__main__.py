#!/usr/bin/env python3
"""
Instana Agent with A2A SDK integration
"""
import asyncio
import os
from typing import Optional

import click
import httpx
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryPushNotifier, InMemoryTaskStore
from a2a.types import AgentCard, AgentSkill, AgentCapabilities

from app.agent import InstanaAgent


def create_agent_card() -> AgentCard:
    """Create the Instana agent card with proper A2A SDK types"""
    skills = [
        AgentSkill(
            id="monitoring",
            name="Application Monitoring",
            description="Real-time application performance monitoring and observability",
            tags=["monitoring", "apm", "observability"]
        ),
        AgentSkill(
            id="infrastructure_monitoring",
            name="Infrastructure Monitoring", 
            description="Infrastructure and system monitoring with detailed metrics",
            tags=["infrastructure", "systems", "metrics"]
        ),
        AgentSkill(
            id="event_analysis",
            name="Event Analysis",
            description="Analysis of application and infrastructure events",
            tags=["events", "analysis", "troubleshooting"]
        ),
        AgentSkill(
            id="alert_management",
            name="Alert Management",
            description="Configuration and management of monitoring alerts",
            tags=["alerts", "notifications", "management"]
        ),
        AgentSkill(
            id="performance_analysis",
            name="Performance Analysis",
            description="Application and system performance analysis and optimization",
            tags=["performance", "optimization", "analysis"]
        ),
        AgentSkill(
            id="kubernetes_monitoring",
            name="Kubernetes Monitoring",
            description="Kubernetes cluster and container monitoring",
            tags=["kubernetes", "containers", "k8s"]
        )
    ]
    
    capabilities = AgentCapabilities(
        streaming=True,
        pushNotifications=True,
        stateTransitionHistory=False
    )
    
    return AgentCard(
        name="Instana Agent",
        description="Handles Instana monitoring and observability operations via MCP protocol",
        url="http://localhost:8005",
        version="1.0.0",
        capabilities=capabilities,
        skills=skills,
        defaultInputModes=["text"],
        defaultOutputModes=["text"]
    )


# Import the agent executor
from app.agent_executor import InstanaAgentExecutor


@click.command()
@click.option("--host", default="localhost", help="Host to bind to")
@click.option("--port", default=8005, help="Port to bind to")
@click.option("--log-level", default="INFO", help="Logging level")
def main(host: str, port: int, log_level: str):
    """Run the Instana Agent server using A2A SDK"""
    
    # Check required environment variables
    instana_base_url = os.getenv("INSTANA_BASE_URL")
    instana_api_token = os.getenv("INSTANA_API_TOKEN")
    
    if not instana_base_url or not instana_api_token:
        print("❌ Missing required environment variables:")
        print("   INSTANA_BASE_URL - Your Instana instance URL")
        print("   INSTANA_API_TOKEN - Your Instana API token")
        print("   GOOGLE_API_KEY - Your Google Gemini API key")
        import sys
        sys.exit(1)
    
    # Create agent card
    agent_card = create_agent_card()
    
    print(f"🚀 Starting Instana Agent on {host}:{port}")
    print(f"📋 Agent Name: {agent_card.name}")
    print(f"📝 Description: {agent_card.description}")
    print(f"🎯 Skills: {', '.join([skill.name for skill in agent_card.skills])}")
    print(f"🔗 Instana Instance: {instana_base_url}")
    
    try:
        # Create the server components following currencyAgent pattern
        httpx_client = httpx.AsyncClient()
        request_handler = DefaultRequestHandler(
            agent_executor=InstanaAgentExecutor(),
            task_store=InMemoryTaskStore(),
            push_notifier=InMemoryPushNotifier(httpx_client),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, 
            http_handler=request_handler
        )

        import uvicorn
        uvicorn.run(server.build(), host=host, port=port)
        
    except Exception as e:
        print(f"❌ Error starting Instana Agent server: {e}")
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main() 