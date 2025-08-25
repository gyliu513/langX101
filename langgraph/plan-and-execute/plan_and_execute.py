#!/usr/bin/env python3
"""
LangGraph Plan-and-Execute Tutorial Implementation

This script demonstrates the plan-and-execute pattern using LangGraph, which is a powerful
approach for breaking down complex tasks into planning and execution phases.

The plan-and-execute pattern consists of:
1. Planning Phase: An LLM creates a detailed plan to solve a problem
2. Execution Phase: The plan is executed step by step, with the ability to replan if needed

Key Benefits:
- Better task decomposition and reasoning
- Ability to handle complex, multi-step problems
- Dynamic replanning when execution fails
- More reliable and interpretable results

Author: LangGraph Tutorial
Modified: AI Assistant
"""

import os
from typing import Dict, List, Tuple, Any
from dotenv import load_dotenv

# Load environment variables (make sure to create a .env file with your API keys)
load_dotenv()

# Import LangGraph and LangChain components
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, END

# ============================================================================
# Configuration and Setup
# ============================================================================

# Initialize the LLM - make sure you have OPENAI_API_KEY in your .env file
llm = ChatOpenAI(
    model="gpt-4",  # You can change this to gpt-3.5-turbo for cost savings
    temperature=0,
    streaming=True
)

# Initialize search tool for research capabilities
search_tool = TavilySearch(max_results=5)

# ============================================================================
# Prompt Templates
# ============================================================================

# Template for the planning phase
PLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are a helpful AI planning assistant. Your job is to create a detailed, 
    step-by-step plan to solve the user's problem. 

    Guidelines:
    1. Break down complex tasks into smaller, manageable steps
    2. Be specific and actionable in your plan
    3. Consider dependencies between steps
    4. Include research steps if external information is needed
    5. Make the plan clear enough that another AI can execute it

    Format your plan as a numbered list of steps."""),
    ("human", "Create a detailed plan to solve this problem: {input}"),
])

# Template for the execution phase
EXECUTOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an AI execution assistant. Your job is to execute the current step 
    in the plan. You have access to tools and should use them when appropriate.

    Current plan: {plan}
    Current step: {current_step}
    Previous results: {results}

    Execute the current step and provide a clear result. If you need to use tools, 
    explain what you're doing and why."""),
    ("human", "Execute step: {current_step}"),
])

# ============================================================================
# Node Functions
# ============================================================================

def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Planning node that creates a detailed execution plan.
    """
    print("🤔 Planning phase...")
    
    # Get the user's input from the last message
    messages = state.get("messages", [])
    if not messages:
        print("❌ No messages found in state")
        return state
    
    user_input = messages[-1].content if messages else ""
    
    # Create the planning prompt
    prompt = PLANNER_PROMPT.format(input=user_input)
    
    # Generate the plan
    response = llm.invoke(prompt)
    
    # Extract the plan from the response
    plan = response.content
    
    print(f"📋 Generated plan:\n{plan}")
    
    # Update state
    state["plan"] = plan
    state["current_step"] = "1"
    state["messages"] = messages + [response]
    
    return state

def executor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execution node that executes the current step in the plan.
    """
    print(f"⚡ Executing step {state.get('current_step', '')}...")
    
    # Parse the plan to get the current step
    plan_lines = state.get("plan", "").split('\n')
    current_step_num = int(state.get("current_step", "1"))
    
    # Find the current step in the plan
    current_step_text = ""
    for line in plan_lines:
        if line.strip().startswith(f"{current_step_num}."):
            current_step_text = line.strip()
            break
    
    if not current_step_text:
        print("❌ Could not find current step in plan")
        return state
    
    print(f"📝 Executing: {current_step_text}")
    
    # Create execution prompt
    prompt = EXECUTOR_PROMPT.format(
        plan=state.get("plan", ""),
        current_step=current_step_text,
        results="\n".join(state.get("results", [])) if state.get("results") else "None"
    )
    
    # Execute the step
    response = llm.invoke(prompt)
    
    # Check if tools are needed
    if "search" in current_step_text.lower() or "research" in current_step_text.lower():
        print("🔍 Research step detected, using search tool...")
        try:
            search_results = search_tool.invoke({"query": current_step_text})
            response = AIMessage(content=f"Research completed: {search_results}")
        except Exception as e:
            print(f"⚠️ Search tool failed: {e}")
            response = AIMessage(content=f"Research step completed (tool unavailable): {response.content}")
    
    print(f"✅ Step {current_step_num} completed: {response.content[:100]}...")
    
    # Update state
    state["results"] = state.get("results", []) + [f"Step {current_step_num}: {response.content}"]
    state["messages"] = state.get("messages", []) + [response]
    
    return state

def should_continue(state: Dict[str, Any]) -> str:
    """
    Determines whether to continue execution or move to the next step.
    """
    plan_lines = state.get("plan", "").split('\n')
    current_step_num = int(state.get("current_step", "1"))
    
    # Count total steps in plan - look for numbered lines
    total_steps = 0
    for line in plan_lines:
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            total_steps += 1
    
    print(f"Debug: Current step {current_step_num}, Total steps found: {total_steps}")
    
    if current_step_num < total_steps:
        # Move to next step
        next_step = str(current_step_num + 1)
        print(f"🔄 Moving to step {next_step}")
        return "next_step"
    else:
        # All steps completed
        print("🎉 All steps completed!")
        return END

def next_step_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates the current step number for the next iteration.
    """
    current_step_num = int(state.get("current_step", "1"))
    state["current_step"] = str(current_step_num + 1)
    return state

# ============================================================================
# Graph Construction
# ============================================================================

def create_plan_execute_graph():
    """
    Creates the LangGraph workflow for plan-and-execute pattern.
    """
    # Create the workflow graph
    workflow = StateGraph(dict)
    
    # Add nodes
    workflow.add_node("planner", planner_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("next_step", next_step_node)
    
    # Add edges
    workflow.add_edge("planner", "executor")
    workflow.add_edge("next_step", "executor")
    
    # Add conditional edges from executor
    workflow.add_conditional_edges(
        "executor",
        should_continue,
        {
            "next_step": "next_step",
            END: END
        }
    )
    
    # Set entry point
    workflow.set_entry_point("planner")
    
    # Compile the workflow
    return workflow.compile()

# ============================================================================
# Main Execution
# ============================================================================

def main():
    """
    Main function to demonstrate the plan-and-execute workflow.
    """
    print("🚀 LangGraph Plan-and-Execute Demo")
    print("=" * 50)
    
    # Check if API key is available
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ Error: OPENAI_API_KEY not found in environment variables")
        print("Please create a .env file with your OpenAI API key:")
        print("OPENAI_API_KEY=your_api_key_here")
        return
    
    # Create the workflow
    app = create_plan_execute_graph()
    
    # Example problem to solve
    problem = """
    I need to plan a weekend trip to San Francisco. I want to visit popular tourist attractions, 
    try local food, and experience the city's culture. I have a budget of $500 and 2 days.
    """
    
    print(f"🎯 Problem: {problem.strip()}")
    print("\n" + "="*50 + "\n")
    
    # Initialize state
    initial_state = {
        "messages": [HumanMessage(content=problem)],
        "plan": "",
        "current_step": "",
        "results": [],
        "replan_count": 0
    }
    
    # Run the workflow
    try:
        result = app.invoke(initial_state)
        
        print("\n" + "="*50)
        print("🏁 Final Results:")
        print("="*50)
        
        # Display final plan
        print(f"\n📋 Final Plan:\n{result['plan']}")
        
        # Display all results
        print(f"\n📊 Execution Results:")
        for i, result_item in enumerate(result['results'], 1):
            print(f"\nStep {i}:")
            print(f"  {result_item}")
        
        print(f"\n🔄 Replanning occurred {result['replan_count']} times")
        
    except Exception as e:
        print(f"❌ Error during execution: {e}")
        print("This might be due to API rate limits, network issues, or configuration problems.")

if __name__ == "__main__":
    main()
