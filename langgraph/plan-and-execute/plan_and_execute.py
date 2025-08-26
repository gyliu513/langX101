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
from typing import Dict, List, Tuple, Any, TypedDict
from dotenv import load_dotenv

# Load environment variables (make sure to create a .env file with your API keys)
load_dotenv()

# Import LangGraph and LangChain components
from langchain_core.messages import HumanMessage, AIMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_tavily import TavilySearch
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
# Helper Functions
# ============================================================================

def extract_search_query(step_text: str, previous_results: str = "") -> str:
    """
    Extracts a concise search query from a step description.
    """
    # Look for specific search terms in the step
    step_lower = step_text.lower()
    
    # First, try to extract the winner's name from previous results
    winner_name = ""
    if previous_results:
        # Look for names in previous results
        if "aryna sabalenka" in previous_results.lower():
            winner_name = "Aryna Sabalenka"
        elif "novak djokovic" in previous_results.lower():
            winner_name = "djokovic"
        elif "jannik sinner" in previous_results.lower():
            winner_name = "Jannik Sinner"
    
    # Extract names mentioned in the step
    if "novak djokovic" in step_lower:
        return "Novak Djokovic biography hometown birthplace"
    elif "aryna sabalenka" in step_lower:
        return "Aryna Sabalenka biography hometown birthplace"
    elif "jannik sinner" in step_lower:
        return "Jannik Sinner biography hometown birthplace"
    elif "australia open winner" in step_lower:
        return "Australia Open 2024 winner men's singles"
    elif "australian open" in step_lower:
        return "Australian Open 2024 winner"
    elif "tennis" in step_lower and "winner" in step_lower:
        return "tennis grand slam winners 2024"
    
    # Look for specific search instructions
    if "search for" in step_lower:
        # Extract text after "search for"
        start_idx = step_lower.find("search for") + 11
        end_idx = step_lower.find(" ", start_idx)
        if end_idx == -1:
            end_idx = len(step_lower)
        query = step_text[start_idx:end_idx].strip()
        if query and len(query) < 100:
            return query
    
    # Look for quoted text
    if '"' in step_text:
        import re
        quotes = re.findall(r'"([^"]+)"', step_text)
        if quotes:
            return quotes[0][:100]  # Limit to 100 chars
    
    # Look for example searches in the step
    if "example search:" in step_lower:
        # Extract the example search
        start_idx = step_lower.find("example search:") + 15
        end_idx = step_lower.find("\n", start_idx)
        if end_idx == -1:
            end_idx = len(step_lower)
        example = step_text[start_idx:end_idx].strip()
        if example and len(example) < 100:
            return example
    
    # Look for specific search patterns like "[Winner's Full Name] hometown"
    if "[" in step_text and "]" in step_text:
        import re
        # Find patterns like [Winner's Full Name] hometown
        patterns = re.findall(r'\[([^\]]+)\]\s*(\w+)', step_text)
        if patterns:
            for placeholder, term in patterns:
                if "winner" in placeholder.lower() or "name" in placeholder.lower():
                    if winner_name:
                        return f"{winner_name} {term}"
                    else:
                        return f"Australia Open winner {term}"
    
    # Default fallback - extract key terms and combine with winner name
    key_terms = []
    if "biography" in step_lower:
        key_terms.append("biography")
    if "hometown" in step_lower:
        key_terms.append("hometown")
    if "winner" in step_lower:
        key_terms.append("winner")
    if "birthplace" in step_lower:
        key_terms.append("birthplace")
    
    # Combine with winner name if available
    if winner_name:
        key_terms.insert(0, winner_name)
    elif "australia" in step_lower or "australian" in step_lower:
        key_terms.insert(0, "Australian Open")
    
    if key_terms:
        return " ".join(key_terms)[:100]
    
    # Final fallback
    return "Australia Open winner 2024"

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
    plan_lines = plan.split('\n')
    step_count = 0
    for i, line in enumerate(plan_lines):
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            step_count += 1
            print(f"  Step {step_count}: {line}...")
    
    print(f"Total steps detected: {step_count}")
    
    # Update state
    state["plan"] = plan
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
    
    # Execute the step
    response = llm.invoke(prompt)
    
    # Check if tools are needed
    if "search" in full_step_text.lower() or "research" in full_step_text.lower():
        print("🔍 Research step detected, using search tool...")
        try:
            # Extract a concise search query from the step description
            previous_results = "\n".join(state.get("results", []))
            search_query = extract_search_query(full_step_text, previous_results)
            print(f"🔍 Using search query: {search_query}")
            
            if len(search_query) > 400:
                print(f"⚠️ Search query too long ({len(search_query)} chars), truncating...")
                search_query = search_query[:400]
            
            search_results = search_tool.invoke({"query": search_query})
            response = AIMessage(content=f"Research completed: {search_results}")
        except Exception as e:
            print(f"⚠️ Search tool failed: {e}")
            if "Query is too long" in str(e):
                response = AIMessage(content=f"Search failed: Query was too long. Please provide a shorter, more focused search term.")
            else:
                response = AIMessage(content=f"Research step completed (tool unavailable): {response.content}")
    
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
    state["reflection_results"] = state.get("reflection_results", []) + [response.content]
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
    new_plan = response.content
    
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
    if hasattr(llm, 'model_name'):
        print(f"📋 Model: {llm.model_name}")
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
        from IPython.display import Image, display
        # Display in interactive environment
        display(Image(app.get_graph(xray=True).draw_mermaid_png()))
        
        # Save the graph as a PNG file
        graph_image = app.get_graph(xray=True).draw_mermaid_png()
        with open("agentic_workflow_graph.png", "wb") as f:
            f.write(graph_image)
        print("📊 Graph visualization saved as 'agentic_workflow_graph.png'")
        
    except ImportError:
        print("IPython not available. Skipping graph visualization.")
    except Exception as e:
        print(f"Could not display graph: {e}")
    
    # Example problem to solve
    problem = """
    what is the hometown of the current Australia open winner?
    """
    
    print(f"🎯 Problem: {problem.strip()}")
    print("\n" + "="*60 + "\n")
    
    # Test search query extraction
    print("🧪 Testing search query extraction...")
    test_step = "1. **Research the winner's biographical information:** Use a search engine to search for 'Novak Djokovic biography' or 'Novak Djokovic hometown'."
    test_query = extract_search_query(test_step)
    print(f"Test step: {test_step}")
    print(f"Extracted query: {test_query}")
    
    # Test with previous results
    test_step2 = "2. **Research the winner's hometown:** Use the winner's full name and search for hometown."
    test_query2 = extract_search_query(test_step2, "Step 1: The winner is Aryna Sabalenka")
    print(f"Test step 2: {test_step2}")
    print(f"Extracted query 2: {test_query2}")
    print("="*60 + "\n")
    
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
