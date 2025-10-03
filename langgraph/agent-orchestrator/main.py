#!/usr/bin/env python3
"""
LangGraph Agent Orchestrator with Task Decomposition

This script combines task decomposition capabilities with agent selection to create
a powerful workflow that:
1. Decomposes complex tasks into smaller, manageable steps
2. Selects the most appropriate agent for each step based on embeddings similarity
3. Executes each step with the selected agent
4. Reflects on the results and adjusts as needed

Key Benefits:
- Better task decomposition and reasoning
- Dynamic agent selection based on step requirements
- Ability to handle complex, multi-step problems
- Continuous reflection and improvement
- Local execution using Ollama models (no API keys required)
- Privacy-preserving as all processing happens locally
"""

import os
import numpy as np
from typing import Dict, List, Tuple, Any, TypedDict, Optional, Union, Literal, Annotated
from dotenv import load_dotenv

# Load environment variables (not required for Ollama but kept for compatibility)
load_dotenv()

# Note: You need to install the following packages:
# pip install langchain langgraph
#
# For Ollama support (choose one):
# Option 1 (recommended): pip install langchain-ollama
# Option 2 (fallback): pip install langchain-community
#
# Make sure Ollama is installed and running:
# 1. Download from https://ollama.com/download
# 2. Run: ollama serve
# 3. Run: ollama pull llama3.1

# Import LangGraph and LangChain components
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command

# Import Ollama components
from langchain_community.llms import Ollama
from langchain_community.embeddings import OllamaEmbeddings
print("Using langchain_community package for Ollama integration")

# ============================================================================
# State Definition
# ============================================================================

class OrchestratorState(TypedDict):
    """State for the agent orchestrator workflow."""
    messages: Annotated[list[BaseMessage], "The messages in the conversation"]
    plan: str
    current_step: str
    current_step_index: int
    total_steps: int
    results: List[str]
    reflection_results: List[Union[str, Any]]  # Allow any type for reflection results
    replan_count: int
    max_replans: int
    workflow_phase: str  # "planning", "agent_selection", "execution", "reflection", "decision"
    selected_agent: str
    selected_agents: List[str]  # Track all agents used in the workflow

# ============================================================================
# Agent Definitions
# ============================================================================

# Define agents with detailed descriptions
AGENTS: dict[str, dict[str, Any]] = {
    "general_conversation": {
        "name": "General Conversation Agent",
        "description": """I am a friendly and engaging conversational agent. I excel at:
- Casual conversations and small talk
- General questions about daily life, hobbies, and interests
- Providing emotional support and encouragement
- Sharing interesting facts and stories
- Helping with general advice and life tips
- Making people feel welcome and comfortable

I'm perfect for users who want to chat casually, need a friendly ear, or have general questions about life, culture, or personal interests.""",
        "examples": [
            "How are you today?",
            "Tell me a joke",
            "What's the weather like?",
            "I'm feeling stressed",
            "What should I do this weekend?",
            "Tell me about your day"
        ]
    },
    
    "technical_support": {
        "name": "Technical Support Agent",
        "description": """I am a technical expert specializing in:
- Programming and software development
- Computer hardware and troubleshooting
- Software installation and configuration
- Debugging code and technical issues
- Explaining technical concepts in simple terms
- Providing step-by-step technical solutions
- Code review and optimization suggestions
- System administration and IT support

I'm ideal for users with technical questions, programming problems, or who need help with computers, software, or digital tools.""",
        "examples": [
            "How do I fix this Python error?",
            "My computer is running slow",
            "How do I install this software?",
            "What's wrong with my code?",
            "How do I set up a database?",
            "Can you help me debug this?"
        ]
    },
    
    "creative_writing": {
        "name": "Creative Writing Agent",
        "description": """I am a creative writing specialist who excels at:
- Storytelling and narrative creation
- Poetry and creative writing
- Brainstorming creative ideas
- Character development and world-building
- Writing prompts and inspiration
- Editing and improving creative content
- Different writing styles and genres
- Creative problem-solving through storytelling

I'm perfect for users who want to write stories, poems, creative content, or need help with creative projects and artistic expression.""",
        "examples": [
            "Help me write a story",
            "Write a poem about love",
            "I need creative inspiration",
            "Help me develop this character",
            "Can you help me with my novel?",
            "Give me a writing prompt"
        ]
    },
    
    "business_consultant": {
        "name": "Business Consultant Agent",
        "description": """I am a business strategy and consulting expert specializing in:
- Business planning and strategy
- Market analysis and research
- Financial planning and budgeting
- Marketing and sales strategies
- Business model development
- Startup advice and entrepreneurship
- Project management and organization
- Professional development and career advice

I'm ideal for entrepreneurs, business professionals, and anyone seeking advice on business matters, career development, or professional growth.""",
        "examples": [
            "How do I start a business?",
            "Help me create a business plan",
            "What's the best marketing strategy?",
            "How do I improve my sales?",
            "Should I invest in this?",
            "Help me with my career goals"
        ]
    },
    
    "health_wellness": {
        "name": "Health & Wellness Agent",
        "description": """I am a health and wellness advisor specializing in:
- General health information and education
- Fitness and exercise advice
- Nutrition and healthy eating
- Mental health and stress management
- Sleep and lifestyle optimization
- Wellness tips and healthy habits
- General medical information (not diagnosis)
- Motivation for healthy living

I'm perfect for users seeking health advice, fitness tips, wellness guidance, or help with maintaining a healthy lifestyle.""",
        "examples": [
            "How can I improve my fitness?",
            "What should I eat for breakfast?",
            "I'm having trouble sleeping",
            "How do I reduce stress?",
            "What exercises should I do?",
            "Help me create a healthy routine"
        ]
    }
}

# ============================================================================
# Configuration and Setup
# ============================================================================

# Initialize Ollama model and embeddings
try:
    # Initialize Ollama model
    llm = Ollama(
        model="llama3.1",  # You can change this to any model you have in Ollama
        base_url="http://localhost:11434",  # Default Ollama URL
        temperature=0.1
    )
    
    # Initialize embeddings for agent selection
    embeddings = OllamaEmbeddings(
        model="llama3.1",  # Use the same model for embeddings
        base_url="http://localhost:11434"
    )
    
    print("✅ Successfully connected to Ollama")
except Exception as e:
    print(f"❌ Error initializing Ollama: {e}")
    print("Please make sure Ollama is running:")
    print("ollama serve")
    exit(1)

# ============================================================================
# Agent Selection Logic
# ============================================================================

class AgentSelector:
    """Uses embeddings to select the most appropriate agent for a task"""
    
    def __init__(self, similarity_threshold: float = 0.3):
        self.embeddings = embeddings
        self.agent_embeddings = {}
        self.similarity_threshold = similarity_threshold
        self._initialize_agent_embeddings()
    
    def _initialize_agent_embeddings(self):
        """Create embeddings for all agent descriptions"""
        print("🔧 Initializing agent embeddings...")
        
        for agent_id, agent_info in AGENTS.items():
            # Create a comprehensive description for embedding
            description = f"{agent_info['name']}: {agent_info['description']}"
            
            # Add examples to the description
            examples_text = "Examples of queries I handle: " + "; ".join(agent_info['examples'])
            full_description = f"{description} {examples_text}"
            
            # Create embedding
            embedding = self.embeddings.embed_query(full_description)
            self.agent_embeddings[agent_id] = embedding
            
            print(f"✅ Created embedding for {agent_info['name']}")
    
    def select_agent(self, task_description: str) -> str:
        """Select the most appropriate agent based on task similarity"""
        
        # Create embedding for task description
        task_embedding = self.embeddings.embed_query(task_description)
        
        # Calculate similarities with all agents
        similarities = {}
        for agent_id, agent_embedding in self.agent_embeddings.items():
            similarity = self._cosine_similarity(task_embedding, agent_embedding)
            similarities[agent_id] = similarity
        
        # Find the agent with highest similarity
        best_agent = max(similarities.items(), key=lambda x: x[1])
        
        print(f"🔍 Agent selection results for task: '{task_description}'")
        for agent_id, similarity in sorted(similarities.items(), key=lambda x: x[1], reverse=True):
            agent_name = AGENTS[agent_id]["name"]
            print(f"  {agent_name}: {similarity:.3f}")
        
        return best_agent[0]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        return dot_product / (norm1 * norm2)

# Initialize agent selector
agent_selector = AgentSelector(similarity_threshold=0.3)

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
    ("system", """You are {agent_name}. {agent_description}

    You are executing a step in a larger plan. Focus on completing this specific step effectively.

    Current plan: {plan}
    Current step ({step_number} of {total_steps}): {current_step}
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

def make_plan(state: OrchestratorState) -> OrchestratorState:
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
    # Handle both string and message object responses
    if hasattr(response, 'content'):
        plan = response.content
    else:
        # If response is a string (as with OllamaLLM)
        plan = response
    
    print(f"📋 Generated plan:\n{plan}")
    
    # Debug: Show plan structure
    print("\n🔍 Plan structure analysis:")
    plan_lines = str(plan).split('\n')
    step_count = 0
    for i, line in enumerate(plan_lines):
        line = line.strip()
        # Check for various step formats: "1.", "Step 1:", "**Step 1:**"
        if (line and line[0].isdigit() and "." in line) or \
           (line.lower().startswith("step") and any(c.isdigit() for c in line)) or \
           (line.startswith("**") and "step" in line.lower() and any(c.isdigit() for c in line)):
            step_count += 1
            print(f"  Step {step_count}: {line}")
    
    print(f"Total steps detected: {step_count}")
    
    # Update state
    state["plan"] = str(plan)
    state["current_step"] = "1"
    state["current_step_index"] = 1
    state["total_steps"] = step_count
    state["workflow_phase"] = "agent_selection"
    
    # Create a proper AIMessage
    if isinstance(response, AIMessage):
        state["messages"] = messages + [response]
    else:
        state["messages"] = messages + [AIMessage(content=str(plan))]
    
    state["selected_agents"] = []
    
    return state

def select_agent_for_step(state: OrchestratorState) -> OrchestratorState:
    """
    Agent selection phase that chooses the most appropriate agent for the current step.
    """
    print(f"🤖 Agent Selection Phase: Selecting agent for step {state.get('current_step', '')}...")
    
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
            (line.startswith("**") and f"{current_step_num}." in line) or
            (line.lower().startswith(f"step {current_step_num}:")) or
            (line.lower().startswith(f"**step {current_step_num}:**"))):
            
            in_current_step = True
            current_step_text = line
            step_content = [line]
        elif in_current_step:
            # Check if we've reached the next step
            next_step_num = current_step_num + 1
            if (line.startswith(f"{next_step_num}.") or
                line.startswith(f"{next_step_num}**") or
                line.startswith(f"{next_step_num} ") or
                (line.startswith("**") and f"{next_step_num}." in line) or
                (line.lower().startswith(f"step {next_step_num}:")) or
                (line.lower().startswith(f"**step {next_step_num}:**"))):
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
    print(f"📝 Current step: {full_step_text}")
    
    # Select the most appropriate agent for this step
    selected_agent = agent_selector.select_agent(full_step_text)
    agent_info = AGENTS[selected_agent]
    
    print(f"✅ Selected agent: {agent_info['name']}")
    print(f"   Specialization: {agent_info['description'][:100]}...")
    
    # Update state
    state["selected_agent"] = selected_agent
    state["selected_agents"] = state.get("selected_agents", []) + [selected_agent]
    state["workflow_phase"] = "execution"
    
    return state

def execute_step_with_agent(state: OrchestratorState) -> OrchestratorState:
    """
    Execution phase that executes the current step using the selected agent.
    """
    # Get the selected agent
    selected_agent = state.get("selected_agent", "general_conversation")
    agent_info = AGENTS[selected_agent]
    
    print(f"⚡ Execution Phase: Executing step {state.get('current_step', '')} with {agent_info['name']}...")
    
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
            (line.startswith("**") and f"{current_step_num}." in line) or
            (line.lower().startswith(f"step {current_step_num}:")) or
            (line.lower().startswith(f"**step {current_step_num}:**"))):
            
            in_current_step = True
            current_step_text = line
            step_content = [line]
        elif in_current_step:
            # Check if we've reached the next step
            next_step_num = current_step_num + 1
            if (line.startswith(f"{next_step_num}.") or
                line.startswith(f"{next_step_num}**") or
                line.startswith(f"{next_step_num} ") or
                (line.startswith("**") and f"{next_step_num}." in line) or
                (line.lower().startswith(f"step {next_step_num}:")) or
                (line.lower().startswith(f"**step {next_step_num}:**"))):
                break
            else:
                step_content.append(line)
    
    if not current_step_text:
        print("❌ Could not find current step in plan")
        return state
    
    # Combine all content for the current step
    full_step_text = "\n".join(step_content)
    
    # Create execution prompt with agent-specific information
    prompt = EXECUTOR_PROMPT.format(
        agent_name=agent_info["name"],
        agent_description=agent_info["description"],
        plan=state.get("plan", ""),
        current_step=full_step_text,
        step_number=current_step_num,
        total_steps=state.get("total_steps", 1),
        results="\n".join(state.get("results", [])) if state.get("results") else "None"
    )
    
    # Execute the step with the selected agent
    response = llm.invoke(prompt)
    
    # Convert to AIMessage if it's a string
    if isinstance(response, AIMessage):
        ai_message = response
    else:
        # If response is a string or other format
        ai_message = AIMessage(content=str(response))
    
    print(f"✅ Step {current_step_num} completed by {agent_info['name']}:")
    print(f"   {ai_message.content}")
    
    # Update state
    state["results"] = state.get("results", []) + [f"Step {current_step_num} ({agent_info['name']}): {ai_message.content}"]
    state["workflow_phase"] = "reflection"
    state["messages"] = state.get("messages", []) + [ai_message]
    
    return state

def reflect_on_results(state: OrchestratorState) -> OrchestratorState:
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
    
    # Handle both string and message object responses
    if isinstance(response, AIMessage):
        ai_message = response
        reflection_content = ai_message.content
    else:
        # If response is a string or other format
        reflection_content = str(response)
        ai_message = AIMessage(content=reflection_content)
    
    print(f"🤔 Reflection:")
    print(f"   {reflection_content}")
    
    # Update state
    state["reflection_results"] = state.get("reflection_results", []) + [reflection_content]
    state["workflow_phase"] = "decision"
    state["messages"] = state.get("messages", []) + [ai_message]
    
    return state

def make_decision(state: OrchestratorState) -> str:
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

def move_to_next_step(state: OrchestratorState) -> OrchestratorState:
    """
    Moves to the next step in the plan.
    """
    current_step_num = int(state.get("current_step", "1"))
    total_steps = state.get("total_steps", 0)
    
    print(f"🔄 Current step {current_step_num}, Total steps: {total_steps}")
    
    if current_step_num < total_steps:
        # Move to next step
        next_step = str(current_step_num + 1)
        state["current_step"] = next_step
        state["current_step_index"] = current_step_num + 1
        state["workflow_phase"] = "agent_selection"  # Go back to agent selection for the next step
        print(f"🔄 Moving to step {next_step}")
        return state
    else:
        # All steps completed
        print("🎉 All steps completed!")
        return state

def replan_step(state: OrchestratorState) -> OrchestratorState:
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
    
    # Handle both string and message object responses
    if isinstance(response, AIMessage):
        ai_message = response
        new_plan = str(ai_message.content)
    else:
        # If response is a string or other format
        new_plan = str(response)
        ai_message = AIMessage(content=new_plan)
    
    print(f"📋 New plan generated:\n{new_plan}")
    
    # Count steps in the new plan
    plan_lines = str(new_plan).split('\n')
    step_count = 0
    for line in plan_lines:
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            step_count += 1
    
    # Update state with new plan
    state["plan"] = new_plan
    state["current_step"] = "1"
    state["current_step_index"] = 1
    state["total_steps"] = step_count
    state["workflow_phase"] = "agent_selection"  # Go back to agent selection for the first step
    state["messages"] = state.get("messages", []) + [ai_message]
    
    return state

def should_end(state: OrchestratorState) -> str:
    """
    Determines whether to continue execution or end the workflow.
    """
    current_step_num = int(state.get("current_step", "1"))
    total_steps = state.get("total_steps", 0)
    
    print(f"Debug: Current step {current_step_num}, Total steps found: {total_steps}")
    
    if current_step_num >= total_steps:
        return END
    else:
        return "continue"
def generate_summary(state: OrchestratorState) -> OrchestratorState:
    """
    Generates a summary of the entire workflow execution.
    """
    print("📊 Generating summary of the workflow execution...")
    
    # Get the original query
    messages = state.get("messages", [])
    original_query = messages[0].content if messages else "Unknown query"
    
    # Get the plan
    plan = state.get("plan", "No plan was created")
    
    # Get the results
    results = state.get("results", [])
    results_text = "\n".join(results) if results else "No results were generated"
    
    # Get the agents used
    selected_agents = state.get("selected_agents", [])
    agent_counts = {}
    for agent in selected_agents:
        agent_counts[agent] = agent_counts.get(agent, 0) + 1
    
    agents_used = []
    for agent_id, count in agent_counts.items():
        agent_name = AGENTS[agent_id]["name"]
        agents_used.append(f"{agent_name} (used {count} times)")
    
    agents_text = "\n".join(agents_used) if agents_used else "No agents were used"
    
    # Create the summary prompt
    summary_prompt = f"""You are a workflow summarization assistant. Create a concise summary of the completed workflow.

Original Query: {original_query}

Plan:
{plan}

Results:
{results_text}

Agents Used:
{agents_text}

Provide a clear, concise summary of what was accomplished, highlighting key insights and results.
"""
    
    # Generate the summary
    response = llm.invoke(summary_prompt)
    
    # Handle both string and message object responses
    if isinstance(response, AIMessage):
        ai_message = response
        summary = ai_message.content
    else:
        # If response is a string or other format
        summary = str(response)
        ai_message = AIMessage(content=summary)
    
    # Create the final summary message
    summary_message = f"""# Workflow Summary

## Original Query
{original_query}

## Execution Summary
{summary}

## Agents Used
{agents_text}

## Steps Completed
{len(results)} of {state.get('total_steps', 0)} steps completed
{state.get('replan_count', 0)} replanning attempts

## Final Results
{results_text}
"""
    
    print("\n" + "="*60)
    print("🏁 Final Summary:")
    print("="*60)
    print(summary_message)
    
    # Add the summary to the state
    final_message = AIMessage(content=summary_message)
    state["messages"] = state.get("messages", []) + [final_message]
    
    return state

# ============================================================================
# Graph Construction
# ============================================================================

def create_orchestrator_graph():
    """
    Creates the LangGraph workflow for the agent orchestrator.
    """
    # Create the workflow graph
    workflow = StateGraph(OrchestratorState)
    
    # Add the main workflow nodes
    workflow.add_node("make_plan", make_plan)
    workflow.add_node("select_agent", select_agent_for_step)
    workflow.add_node("execute_step", execute_step_with_agent)
    workflow.add_node("reflect", reflect_on_results)
    workflow.add_node("next_step", move_to_next_step)
    workflow.add_node("replan", replan_step)
    workflow.add_node("generate_summary", generate_summary)
    
    # Set the starting point
    workflow.add_edge(START, "make_plan")
    
    # From make_plan, go to select_agent
    workflow.add_edge("make_plan", "select_agent")
    
    # From select_agent, go to execute_step
    workflow.add_edge("select_agent", "execute_step")
    
    # From execute_step, go to reflect
    workflow.add_edge("execute_step", "reflect")
    
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
            "continue": "select_agent",
            END: "generate_summary"
        }
    )
    
    # From replan, go back to select_agent
    workflow.add_edge("replan", "select_agent")
    
    # From generate_summary, go to END
    workflow.add_edge("generate_summary", END)
    
    # Compile the workflow
    return workflow.compile()

# ============================================================================
# Main Execution
# ============================================================================

def main():
    """
    Main function to demonstrate the agent orchestrator.
    """
    print("🚀 LangGraph Agent Orchestrator Demo")
    print("=" * 60)
    print("Workflow: Make Plan → Select Agent → Execute Step → Reflect → Decision → Continue/Replan")
    print("=" * 60)
    
    # Show which model is being used
    print(f"🤖 Using LLM: {type(llm).__name__}")
    print(f"📋 Model: {llm.model}")
    print("=" * 60)
    
    # Check if Ollama is running
    try:
        import requests
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code != 200:
            print("❌ Error: Ollama is not responding properly.")
            print("Please make sure Ollama is running:")
            print("ollama serve")
            return
    except Exception as e:
        print("❌ Error: Cannot connect to Ollama.")
        print("Please make sure Ollama is running:")
        print("ollama serve")
        print(f"Error details: {e}")
        return
    
    # Create the workflow
    app = create_orchestrator_graph()
    
    # Example problem to solve
    problem = """
    I want to create a personal finance tracking app. Help me understand what features it should have, how to implement it, and what technologies to use.
    """
    
    print("🤖 Using local Ollama model for all LLM operations")
    print(f"📋 Model: {llm.model}")
    
    print(f"🎯 Problem: {problem.strip()}")
    print("\n" + "="*60 + "\n")
    
    # Initialize state
    initial_state = OrchestratorState(
        messages=[HumanMessage(content=problem)],
        plan="",
        current_step="",
        current_step_index=0,
        total_steps=0,
        results=[],
        reflection_results=[],
        replan_count=0,
        max_replans=3,
        workflow_phase="planning",
        selected_agent="",
        selected_agents=[]
    )
    
    # Run the workflow
    try:
        result = app.invoke(initial_state)
        print("\n" + "="*60)
        print("🏁 Workflow completed successfully!")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Error during execution: {e}")
        print("This might be due to API rate limits, network issues, or configuration problems.")

if __name__ == "__main__":
    main()
