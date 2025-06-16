import logging
from typing import AsyncIterable, Dict, Any, List

from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from hello_agents.common.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class HelloWorldAgent(BaseAgent):
    """A simple Hello World agent using LangGraph."""
    
    def __init__(self):
        super().__init__(
            agent_name="HelloWorldAgent",
            description="A simple agent that greets users",
            content_types=["text", "text/plain"],
        )
        
        # Initialize the LLM
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",
            temperature=0,
        )
        
        # Create a simple graph
        self.graph = self._build_graph()
        
        # Initialize memory saver for state persistence
        self.memory = MemorySaver()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow."""
        
        # Define the state schema
        class State(dict):
            messages: List
        
        # Define the nodes
        def greet(state: State) -> State:
            """Generate a greeting based on the input."""
            messages = state["messages"]
            response = self.llm.invoke(messages)
            return {"messages": messages + [response]}
        
        # Create the graph
        workflow = StateGraph(State)
        
        # Add the node
        workflow.add_node("greet", greet)
        
        # Set the entry point
        workflow.set_entry_point("greet")
        
        # Set the exit point
        workflow.add_edge("greet", END)
        
        # Compile the graph
        return workflow.compile()
    
    async def stream(
        self, query: str, context_id: str, task_id: str
    ) -> AsyncIterable[Dict[str, Any]]:
        """Stream the agent's response."""
        logger.info(f"Processing query: {query} for context: {context_id}, task: {task_id}")
        
        # Create the initial state
        initial_state = {
            "messages": [
                HumanMessage(content=f"Respond with a friendly greeting to: {query}")
            ]
        }
        
        # Create config with thread ID for state persistence
        config = {"configurable": {"thread_id": context_id}}
        
        # Process intermediate steps
        for step in self.graph.stream(initial_state, config):
            # Yield intermediate progress
            yield {
                "is_task_complete": False,
                "require_user_input": False,
                "content": "Processing your request..."
            }
        
        # Get the final state
        final_state = self.graph.get_state(config)
        messages = final_state["messages"]
        
        # Extract the AI's response
        for message in messages:
            if isinstance(message, AIMessage):
                # Return the final result
                yield {
                    "is_task_complete": True,
                    "require_user_input": False,
                    "content": message.content
                }
                return
        
        # Fallback response if no AI message was found
        yield {
            "is_task_complete": True,
            "require_user_input": False,
            "content": "Hello! I'm the Hello World Agent."
        }