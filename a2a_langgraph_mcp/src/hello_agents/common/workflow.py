import logging
import uuid
from enum import Enum
from typing import Dict, Any, AsyncIterable, Optional
from uuid import uuid4

import networkx as nx

logger = logging.getLogger(__name__)


class Status(Enum):
    """Represents the status of a workflow and its associated node."""
    READY = 'READY'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    PAUSED = 'PAUSED'
    INITIALIZED = 'INITIALIZED'


class WorkflowNode:
    """Represents a single node in a workflow graph."""

    def __init__(
        self,
        task: str,
        node_key: str | None = None,
        node_label: str | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.node_key = node_key
        self.node_label = node_label
        self.task = task
        self.results = None
        self.state = Status.READY
        self.agent = None

    def set_agent(self, agent):
        """Set the agent for this node."""
        self.agent = agent

    async def run_node(
        self,
        query: str,
        task_id: str,
        context_id: str,
    ) -> AsyncIterable[Dict[str, Any]]:
        """Execute the node's task using its assigned agent."""
        logger.info(f'Executing node {self.id} with task: {self.task}')
        
        if not self.agent:
            raise ValueError(f"No agent assigned to node {self.id}")
            
        self.state = Status.RUNNING
        
        async for chunk in self.agent.stream(query, context_id, task_id):
            # Store the result if it's the final response
            if chunk.get('is_task_complete', False):
                self.results = chunk.get('content')
                self.state = Status.COMPLETED
            yield chunk


class WorkflowGraph:
    """Represents a graph of workflow nodes."""

    def __init__(self):
        self.graph = nx.DiGraph()
        self.nodes = {}
        self.latest_node = None
        self.state = Status.INITIALIZED
        self.paused_node_id = None

    def add_node(self, node: WorkflowNode) -> None:
        """Add a node to the graph."""
        logger.info(f'Adding node {node.id}')
        self.graph.add_node(node.id, query=node.task)
        self.nodes[node.id] = node
        self.latest_node = node.id
        return node

    def add_edge(self, from_node_id: str, to_node_id: str) -> None:
        """Add an edge between two nodes."""
        if from_node_id not in self.nodes or to_node_id not in self.nodes:
            raise ValueError('Invalid node IDs')

        self.graph.add_edge(from_node_id, to_node_id)

    async def run_workflow(
        self, start_node_id: Optional[str] = None
    ) -> AsyncIterable[Dict[str, Any]]:
        """Execute the workflow starting from the specified node."""
        logger.info('Executing workflow graph')
        
        if not start_node_id or start_node_id not in self.nodes:
            start_nodes = [n for n, d in self.graph.in_degree() if d == 0]
        else:
            start_nodes = [start_node_id]

        applicable_graph = set()

        for node_id in start_nodes:
            applicable_graph.add(node_id)
            applicable_graph.update(nx.descendants(self.graph, node_id))

        complete_graph = list(nx.topological_sort(self.graph))
        sub_graph = [n for n in complete_graph if n in applicable_graph]
        logger.info(f'Sub graph {sub_graph} size {len(sub_graph)}')
        
        self.state = Status.RUNNING
        
        for node_id in sub_graph:
            node = self.nodes[node_id]
            query = self.graph.nodes[node_id].get('query')
            task_id = self.graph.nodes[node_id].get('task_id')
            context_id = self.graph.nodes[node_id].get('context_id')
            
            async for chunk in node.run_node(query, task_id, context_id):
                if node.state == Status.PAUSED:
                    self.state = Status.PAUSED
                    self.paused_node_id = node.id
                    break
                yield chunk
                
            if self.state == Status.PAUSED:
                break
                
        if self.state == Status.RUNNING:
            self.state = Status.COMPLETED

    def set_node_attributes(self, node_id, attr_val):
        """Set attributes for a node."""
        nx.set_node_attributes(self.graph, {node_id: attr_val})

    def is_empty(self) -> bool:
        """Check if the graph is empty."""
        return self.graph.number_of_nodes() == 0