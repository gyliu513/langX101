#!/usr/bin/env python3
"""
LangGraph Agentic Workflow Implementation

This script implements the agentic workflow pattern using LangGraph, following the
agentic workflow diagram with planning, execution, and reflection phases.

The agentic workflow consists of:
1. Planning Phase: An LLM creates a detailed plan to solve a problem
2. Execution Phase: The plan is executed step by step using available tools
3. Reflection Phase: Results are evaluated to determine if they meet requirements
4. Decision Phase: Either continue with next steps or replan if results are not satisfactory

Key Benefits:
- Better task decomposition and reasoning
- Ability to handle complex, multi-step problems
- Dynamic replanning when execution fails
- Continuous reflection and improvement
- More reliable and interpretable results
"""

import os
from typing import Dict, List, Tuple, Any, TypedDict, Optional, Union
from dotenv import load_dotenv

# Load environment variables (make sure to create a .env file with your API keys)
load_dotenv()

# Import LangGraph and LangChain components
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
# Comment out Tavily if not installed
# from langchain_tavily import TavilySearch
from langgraph.graph import StateGraph, START, END

# ============================================================================
# State Definition
# ============================================================================

class AgenticWorkflow(TypedDict):
    """State for the agentic workflow with planning, execution, and reflection."""
    messages: List[Any]
    plan: str
    current_step: str
    results: List[str]
    reflection_results: List[str]
    replan_count: int
    max_replans: int
    workflow_phase: str  # "planning", "execution", "reflection", "decision"

# ============================================================================
# Configuration and Setup
# ============================================================================

# Initialize the LLM - make sure you have GOOGLE_API_KEY in your .env file
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("⚠️  GOOGLE_API_KEY not set. Using default configuration.")
    # Use default configuration without explicit API key
    # The ChatGoogleGenerativeAI will try to find the key from other sources
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        temperature=0
    )
else:
    llm = ChatGoogleGenerativeAI(
        model="gemini-1.5-flash",
        google_api_key=api_key,
        temperature=0
    )

# Initialize search tool for research capabilities
# Comment out if Tavily is not installed
# search_tool = TavilySearch(max_results=5)

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
    6. Number each step clearly (1., 2., 3., etc.)
    7. Define clear success criteria for each step
    8. Keep step descriptions concise and focused
    9. Use simple formatting that's easy to parse
    10. For research steps, specify the exact search terms to use

    Format your plan as a numbered list of steps. Each step should start with a number and period (e.g., "1.", "2.", "3.").
    Keep the format simple and consistent.
    
    For research steps, be specific about what to search for, not how to search."""),
    ("human", "Create a detailed plan to solve this problem: {input}"),
])

# Template for the execution phase
EXECUTOR_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an AI execution assistant. Your job is to execute the current step 
    in the plan. You have access to tools and should use them when appropriate.

    Current plan: {plan}
    Current step: {current_step}
    Previous results: {results}

    Execute the current step and provide a clear result. Focus on the specific action 
    required by the step, not on explaining the step itself. Be concise and actionable.
    
    If the step requires research or search, focus on the core information needed.
    If the step requires verification, focus on the verification process and results.
    
    Return your result in a clear, structured format that can be evaluated."""),
    ("human", "Execute step: {current_step}"),
])

# Template for the reflection phase
REFLECTION_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an AI reflection assistant. Your job is to evaluate the results 
    of the current step execution and determine if the results meet the expected criteria.

    Current step: {current_step}
    Step result: {step_result}
    Overall plan: {plan}
    Previous results: {results}

    Evaluate the result based on:
    1. Completeness: Does the result fully address the step requirements?
    2. Accuracy: Is the information correct and reliable?
    3. Relevance: Does the result contribute to the overall goal?
    4. Quality: Is the result well-structured and useful?

    Provide a clear assessment: "Result OK" or "Result NOT OK" with detailed reasoning.
    If the result is NOT OK, explain what went wrong and what needs to be improved."""),
    ("human", "Evaluate the result of this step execution."),
])

# Template for the replanning phase
REPLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an AI replanning assistant. Your job is to analyze the current situation
    and create a new plan when the original plan has failed or needs modification.

    Original plan: {original_plan}
    Current step that failed: {failed_step}
    Results from successful steps: {successful_results}
    Reflection analysis: {reflection_analysis}

    Create a new plan that:
    1. Builds on the successful steps already completed
    2. Addresses the specific issues identified in the reflection
    3. Provides alternative approaches for the failed step
    4. Maintains the overall goal of the original request
    5. Includes improved success criteria
    6. Uses simple, parseable formatting

    Format your new plan as a numbered list of steps. Each step should start with a number and period (e.g., "1.", "2.", "3.").
    Keep the format simple and consistent for easy parsing."""),
    ("human", "Create a new plan to address the failure and continue execution."),
])

# ============================================================================
# Node Functions
# ============================================================================

def make_plan(state: AgenticWorkflow) -> AgenticWorkflow:
    """
    Planning phase that creates a detailed execution plan.
    """
    print("🤔 Planning Phase: Making a plan...")
    
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
    
    # Debug: Show plan structure
    print("\n🔍 Plan structure analysis:")
    plan_lines = str(plan).split('\n')
    step_count = 0
    for i, line in enumerate(plan_lines):
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            step_count += 1
            print(f"  Step {step_count}: {line}")
    
    print(f"Total steps detected: {step_count}")
    
    # Update state
    state["plan"] = str(plan)
    state["current_step"] = "1"
    state["workflow_phase"] = "execution"
    state["messages"] = messages + [response]
    
    return state

def execute_actions_with_tools(state: AgenticWorkflow) -> AgenticWorkflow:
    """
    Execution phase that executes the current step in the plan using available tools.
    """
    print(f"⚡ Execution Phase: Executing actions with tools for step {state.get('current_step', '')}...")
    
    # Parse the plan to get the current step
    plan_lines = state.get("plan", "").split('\n')
    current_step_num = int(state.get("current_step", "1"))
    
    # Find the current step in the plan - handle various formats
    current_step_text = ""
    step_content = []
    in_current_step = False
    
    for line in plan_lines:
        line = line.strip()
        if not line:
            continue
            
        # Check for step start patterns
        if (line.startswith(f"{current_step_num}.") or 
            line.startswith(f"{current_step_num}**") or
            line.startswith(f"{current_step_num} ") or
            (line.startswith("**") and f"{current_step_num}." in line)):
            
            in_current_step = True
            current_step_text = line
            step_content = [line]
        elif in_current_step:
            # Check if we've reached the next step
            next_step_num = current_step_num + 1
            if (line.startswith(f"{next_step_num}.") or 
                line.startswith(f"{next_step_num}**") or
                line.startswith(f"{next_step_num} ") or
                (line.startswith("**") and f"{next_step_num}." in line)):
                break
            else:
                step_content.append(line)
    
    if not current_step_text:
        print("❌ Could not find current step in plan")
        print(f"Looking for step {current_step_num}, but plan format may be different")
        print("Plan preview:")
        for i, line in enumerate(plan_lines):
            print(f"  {i}: {line}")
        return state
    
    # Combine all content for the current step
    full_step_text = "\n".join(step_content)
    print(f"📝 Executing: {full_step_text}")
    
    # Create execution prompt
    prompt = EXECUTOR_PROMPT.format(
        plan=state.get("plan", ""),
        current_step=full_step_text,
        results="\n".join(state.get("results", [])) if state.get("results") else "None"
    )
    
    print(f"📝 Prompt for this execution: {prompt}")
    # Execute the step
    response = llm.invoke(prompt)
    
    # Check if tools are needed
    if "search" in full_step_text.lower() or "research" in full_step_text.lower():
        print("🔍 Research step detected, using search tool...")
        try:
            # For this general agent, we'll use the LLM to simulate search results
            # since we've removed the specific search query extraction
            if state.get("results"):
                full_step_text = (
                    f"{full_step_text}\n with the following results:\n" +
                    "\n".join(state["results"])
    )
            print(f"📝 full_step_text for search: {full_step_text}")
            search_response = llm.invoke(
                f"You are a search engine. Provide relevant information for: {full_step_text}"
            )
            response = AIMessage(content=f"Research completed: {search_response.content}")
        except Exception as e:
            print(f"⚠️ Search simulation failed: {e}")
            response = AIMessage(content=f"Research step completed (simulated): {response.content}")
    
    print(f"✅ Step {current_step_num} completed:")
    print(f"   {response.content}")
    
    # Update state
    state["results"] = state.get("results", []) + [f"Step {current_step_num}: {response.content}"]
    state["workflow_phase"] = "reflection"
    state["messages"] = state.get("messages", []) + [response]
    
    return state

def reflect_on_results(state: AgenticWorkflow) -> AgenticWorkflow:
    """
    Reflection phase that evaluates the results of the current step execution.
    """
    print("🔍 Reflection Phase: Reflecting on results of actions...")
    
    # Get the current step and its result
    current_step = state.get("current_step", "")
    results = state.get("results", [])
    
    if not results:
        print("❌ No results to reflect on")
        return state
    
    # Get the most recent result
    current_result = results[-1]
    
    # Create reflection prompt
    prompt = REFLECTION_PROMPT.format(
        current_step=current_step,
        step_result=current_result,
        plan=state.get("plan", ""),
        results="\n".join(results[:-1]) if len(results) > 1 else "None"
    )
    
    # Generate reflection
    response = llm.invoke(prompt)
    
    print(f"🤔 Reflection:")
    print(f"   {response.content}")
    
    # Update state
    reflection_content = str(response.content)
    state["reflection_results"] = state.get("reflection_results", []) + [reflection_content]
    state["workflow_phase"] = "decision"
    state["messages"] = state.get("messages", []) + [response]
    
    return state

def make_decision(state: AgenticWorkflow) -> str:
    """
    Decision phase that determines whether to continue execution or replan.
    """
    print("🎯 Decision Phase: Evaluating if result is OK...")
    
    # Get the latest reflection
    reflection_results = state.get("reflection_results", [])
    if not reflection_results:
        print("❌ No reflection results found")
        return "replan"
    
    latest_reflection = reflection_results[-1].lower()
    
    # Check if the result is OK based on reflection
    if "result ok" in latest_reflection or "result is ok" in latest_reflection:
        print("✅ Result is OK - continuing to next step")
        return "next_step"
    else:
        print("❌ Result is NOT OK - need to replan")
        return "replan"

def move_to_next_step(state: AgenticWorkflow) -> AgenticWorkflow:
    """
    Moves to the next step in the plan.
    """
    plan_lines = state.get("plan", "").split('\n')
    current_step_num = int(state.get("current_step", "1"))
    
    # Count total steps in plan - handle various formats
    total_steps = 0
    for line in plan_lines:
        line = line.strip()
        if not line:
            continue
        # Check for various step number patterns
        if (line and line[0].isdigit() and "." in line) or \
           (line.startswith("**") and any(char.isdigit() for char in line[:10])):
            total_steps += 1
    
    print(f"🔄 Current step {current_step_num}, Total steps: {total_steps}")
    
    if current_step_num < total_steps:
        # Move to next step
        next_step = str(current_step_num + 1)
        state["current_step"] = next_step
        state["workflow_phase"] = "execution"
        print(f"🔄 Moving to step {next_step}")
        return state
    else:
        # All steps completed
        print("🎉 All steps completed!")
        return state

def replan_step(state: AgenticWorkflow) -> AgenticWorkflow:
    """
    Replanning phase that creates a new plan when execution fails.
    """
    print("🔄 Replanning Phase: Making a new plan...")
    
    # Increment replan count
    current_replan_count = state.get("replan_count", 0) + 1
    state["replan_count"] = current_replan_count
    
    if current_replan_count > state.get("max_replans", 3):
        print(f"❌ Maximum replanning attempts ({state.get('max_replans', 3)}) reached")
        return state
    
    print(f"🔄 Attempting replan #{current_replan_count}")
    
    # Get the reflection analysis
    reflection_results = state.get("reflection_results", [])
    reflection_analysis = reflection_results[-1] if reflection_results else "Execution failed, need to replan"
    
    # Create replanning prompt
    prompt = REPLANNER_PROMPT.format(
        original_plan=state.get("plan", ""),
        failed_step=state.get("current_step", ""),
        successful_results="\n".join(state.get("results", [])),
        reflection_analysis=reflection_analysis
    )
    
    # Generate new plan
    response = llm.invoke(prompt)
    new_plan = str(response.content)
    
    print(f"📋 New plan generated:\n{new_plan}")
    
    # Update state with new plan
    state["plan"] = new_plan
    state["current_step"] = "1"  # Start from beginning with new plan
    state["workflow_phase"] = "execution"
    state["messages"] = state.get("messages", []) + [response]
    
    return state

def should_end(state: AgenticWorkflow) -> str:
    """
    Determines whether to continue execution or end the workflow.
    """
    plan_lines = state.get("plan", "").split('\n')
    current_step_num = int(state.get("current_step", "1"))
    
    # Count total steps in plan - handle various formats
    total_steps = 0
    for line in plan_lines:
        line = line.strip()
        if not line:
            continue
        # Check for various step number patterns
        if (line and line[0].isdigit() and "." in line) or \
           (line.startswith("**") and any(char.isdigit() for char in line[:10])):
            total_steps += 1
    
    print(f"Debug: Current step {current_step_num}, Total steps found: {total_steps}")
    
    if current_step_num >= total_steps and state.get("workflow_phase") == "execution":
        return END
    else:
        return "continue"

# ============================================================================
# Graph Construction
# ============================================================================

def create_agentic_workflow_graph():
    """
    Creates the LangGraph workflow for the agentic workflow pattern.
    """
    # Create the workflow graph
    workflow = StateGraph(AgenticWorkflow)
    
    # Add the main workflow nodes
    workflow.add_node("make_plan", make_plan)
    workflow.add_node("execute_actions", execute_actions_with_tools)
    workflow.add_node("reflect", reflect_on_results)
    workflow.add_node("next_step", move_to_next_step)
    workflow.add_node("replan", replan_step)
    
    # Set the starting point
    workflow.add_edge(START, "make_plan")
    
    # From make_plan, go to execute_actions
    workflow.add_edge("make_plan", "execute_actions")
    
    # From execute_actions, go to reflect
    workflow.add_edge("execute_actions", "reflect")
    
    # From reflect, make a decision
    workflow.add_conditional_edges(
        "reflect",
        make_decision,
        {
            "next_step": "next_step",
            "replan": "replan"
        }
    )
    
    # From next_step, either continue or end
    workflow.add_conditional_edges(
        "next_step",
        should_end,
        {
            "continue": "execute_actions",
            END: END
        }
    )
    
    # From replan, go back to execute_actions
    workflow.add_edge("replan", "execute_actions")
    
    # Compile the workflow
    return workflow.compile()

# ============================================================================
# Main Execution
# ============================================================================

def main():
    """
    Main function to demonstrate the agentic workflow.
    """
    print("🚀 LangGraph Agentic Workflow Demo")
    print("=" * 60)
    print("Workflow: Make Plan → Execute Actions → Reflect → Decision → Continue/Replan")
    print("=" * 60)
    
    # Show which model is being used
    print(f"🤖 Using LLM: {type(llm).__name__}")
    print(f"📋 Model: {llm.model}")
    print("=" * 60)
    
    # Check if API key is available
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ Error: GOOGLE_API_KEY not found in environment variables")
        print("Please create a .env file with your Google API key:")
        print("GOOGLE_API_KEY=your_api_key_here")
        return
    
    # Create the workflow
    app = create_agentic_workflow_graph()
    
    # Visualize the graph and save as image
    try:
        # Skip visualization if IPython is not available
        print("📊 Graph visualization skipped (requires IPython)")
    except Exception as e:
        print(f"Could not display graph: {e}")
    
    # Example problem to solve
    problem = """
    What is the hometown of the 2023 Australia open winner for men's singles?
    """
    
    print(f"🎯 Problem: {problem.strip()}")
    print("\n" + "="*60 + "\n")
    
    # Initialize state
    initial_state = AgenticWorkflow(
        messages=[HumanMessage(content=problem)],
        plan="",
        current_step="",
        results=[],
        reflection_results=[],
        replan_count=0,
        max_replans=3,
        workflow_phase="planning"
    )
    
    # Run the workflow
    try:
        result = app.invoke(initial_state)
        
        print("\n" + "="*60)
        print("🏁 Final Results:")
        print("="*60)
        
        # Display final plan
        print(f"\n📋 Final Plan:\n{result['plan']}")
        
        # Display all results
        print(f"\n📊 Execution Results:")
        for i, result_item in enumerate(result['results'], 1):
            print(f"\nStep {i}:")
            print(f"  {result_item}")
        
        # Display reflection results
        print(f"\n🤔 Reflection Results:")
        for i, reflection in enumerate(result['reflection_results'], 1):
            print(f"\nReflection {i}:")
            print(f"  {reflection}")
        
        print(f"\n🔄 Replanning occurred {result['replan_count']} times")
        print(f"🎯 Final workflow phase: {result['workflow_phase']}")
        
    except Exception as e:
        print(f"❌ Error during execution: {e}")
        print("This might be due to API rate limits, network issues, or configuration problems.")

if __name__ == "__main__":
    main()
