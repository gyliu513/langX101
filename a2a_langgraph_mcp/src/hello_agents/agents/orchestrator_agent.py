import logging
import uuid
from typing import AsyncIterable, Dict, Any, List

from hello_agents.common.base_agent import BaseAgent
from hello_agents.common.workflow import WorkflowGraph, WorkflowNode, Status
from hello_agents.mcp.client import get_client

logger = logging.getLogger(__name__)


class OrchestratorAgent(BaseAgent):
    """Orchestrator Agent that coordinates between multiple agents."""
    
    def __init__(self, mcp_host="localhost", mcp_port=10000):
        super().__init__(
            agent_name="OrchestratorAgent",
            description="Coordinates tasks between multiple agents",
            content_types=["text", "text/plain"],
        )
        
        self.mcp_client = get_client(host=mcp_host, port=mcp_port)
        self.graph = None
        self.results = []
        self.context_id = None
    
    def clear_state(self):
        """Clear the agent's state."""
        self.graph = None
        self.results.clear()
    
    def add_graph_node(
        self,
        task_id: str,
        context_id: str,
        query: str,
        agent: BaseAgent,
        node_id: str = None,
        node_key: str = None,
        node_label: str = None,
    ) -> WorkflowNode:
        """Add a node to the workflow graph."""
        node = WorkflowNode(
            task=query, 
            node_key=node_key, 
            node_label=node_label
        )
        node.set_agent(agent)
        self.graph.add_node(node)
        
        if node_id:
            self.graph.add_edge(node_id, node.id)
            
        self.graph.set_node_attributes(
            node.id, 
            {"task_id": task_id, "context_id": context_id, "query": query}
        )
        
        return node
    
    async def stream(
        self, query: str, context_id: str, task_id: str
    ) -> AsyncIterable[Dict[str, Any]]:
        """Stream the orchestrator's response."""
        logger.info(f"Orchestrating query: {query} for context: {context_id}, task: {task_id}")
        
        if not query:
            raise ValueError("Query cannot be empty")
            
        if self.context_id != context_id:
            # Clear state when the context changes
            self.clear_state()
            self.context_id = context_id
        
        # Initialize the workflow graph if it doesn't exist
        if not self.graph:
            self.graph = WorkflowGraph()
            
            # For this simple example, we'll just use the HelloWorldAgent
            # In a real implementation, we would discover agents via MCP
            from hello_agents.agents.hello_agent import HelloWorldAgent
            hello_agent = HelloWorldAgent()
            
            # Add the hello agent node to the graph
            hello_node = self.add_graph_node(
                task_id=task_id,
                context_id=context_id,
                query=query,
                agent=hello_agent,
                node_key="hello",
                node_label="Hello World Agent",
            )
            
            start_node_id = hello_node.id
        else:
            # If the graph exists, use the first node
            start_node_id = next(iter(self.graph.nodes.keys()))
            self.graph.set_node_attributes(
                node_id=start_node_id,
                attr_val={"query": query, "task_id": task_id, "context_id": context_id}
            )
        
        # First, yield a processing message
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": f"{self.agent_name}: Processing your request..."
        }
        
        # Execute the workflow
        async for chunk in self.graph.run_workflow(start_node_id=start_node_id):
            # Pass through the chunk from the agent
            yield chunk
            
        # If the workflow is complete, generate a summary
        if self.graph.state == Status.COMPLETED:
            # Collect results from all nodes
            for node_id, node in self.graph.nodes.items():
                if node.results:
                    self.results.append(node.results)
            
            # In a real implementation, we would generate a summary of the results
            # For this simple example, we'll just return the results directly
            if self.results:
                yield {
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": f"Orchestration complete. Results: {self.results}"
                }
            else:
                yield {
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": "Orchestration complete, but no results were produced."
                }