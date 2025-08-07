import os
from typing import Literal, List, Dict, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.types import Command
import numpy as np

# Load environment variables
load_dotenv()

# Define custom state that includes selected agents
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], "The messages in the conversation"]
    selected_agents: Annotated[list[str], "The selected agents for multi-agent requests"]

# Initialize OpenAI model and embeddings
model = ChatOpenAI(
    model="gpt-3.5-turbo",
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    temperature=0.1
)

embeddings = OpenAIEmbeddings(
    openai_api_key=os.getenv("OPENAI_API_KEY")
)

# Define agents with detailed descriptions
AGENTS = {
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

class AgentSelector:
    """Uses embeddings to select the most appropriate agent(s) for a user query"""
    
    def __init__(self, similarity_threshold: float = 0.3, max_agents: int = 3):
        self.embeddings = embeddings
        self.agent_embeddings = {}
        self.similarity_threshold = similarity_threshold
        self.max_agents = max_agents
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
    
    def select_agent(self, user_message: str) -> str:
        """Select the most appropriate agent based on user message similarity (single agent mode)"""
        
        # Create embedding for user message
        user_embedding = self.embeddings.embed_query(user_message)
        
        # Calculate similarities with all agents
        similarities = {}
        for agent_id, agent_embedding in self.agent_embeddings.items():
            similarity = self._cosine_similarity(user_embedding, agent_embedding)
            similarities[agent_id] = similarity
        
        # Find the agent with highest similarity
        best_agent = max(similarities.items(), key=lambda x: x[1])
        
        print(f"🔍 Agent selection results:")
        for agent_id, similarity in sorted(similarities.items(), key=lambda x: x[1], reverse=True):
            agent_name = AGENTS[agent_id]["name"]
            print(f"  {agent_name}: {similarity:.3f}")
        
        return best_agent[0]
    
    def select_multiple_agents(self, user_message: str) -> List[str]:
        """Select multiple appropriate agents based on user message similarity"""
        
        # Create embedding for user message
        user_embedding = self.embeddings.embed_query(user_message)
        
        # Calculate similarities with all agents
        similarities = {}
        for agent_id, agent_embedding in self.agent_embeddings.items():
            similarity = self._cosine_similarity(user_embedding, agent_embedding)
            similarities[agent_id] = similarity
        
        # Sort agents by similarity score
        sorted_agents = sorted(similarities.items(), key=lambda x: x[1], reverse=True)
        
        # Select agents that meet the threshold and are within max_agents limit
        selected_agents = []
        for agent_id, similarity in sorted_agents:
            if similarity >= self.similarity_threshold and len(selected_agents) < self.max_agents:
                selected_agents.append(agent_id)
        
        # If no agents meet the threshold, at least return the top agent
        if not selected_agents and sorted_agents:
            selected_agents = [sorted_agents[0][0]]
        
        print(f"🔍 Multi-agent selection results:")
        print(f"   📊 Similarity Analysis:")
        for agent_id, similarity in sorted_agents:
            agent_name = AGENTS[agent_id]["name"]
            status = "✅ SELECTED" if agent_id in selected_agents else "❌ NOT SELECTED"
            threshold_status = "≥" if similarity >= self.similarity_threshold else "<"
            print(f"     {agent_name}: {similarity:.3f} {threshold_status} {self.similarity_threshold} {status}")
        
        print(f"\n📋 Selection Criteria:")
        print(f"   • Similarity threshold: {self.similarity_threshold}")
        print(f"   • Max agents: {self.max_agents}")
        print(f"   • Agents meeting threshold: {len([a for a, s in sorted_agents if s >= self.similarity_threshold])}")
        print(f"   • Agents selected: {len(selected_agents)}")
        
        return selected_agents
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        return dot_product / (norm1 * norm2)

# Initialize agent selector with multi-agent support
# similarity_threshold: Minimum similarity score to consider an agent (0.3 = 30% similarity)
# max_agents: Maximum number of agents to select for multi-agent requests
agent_selector = AgentSelector(similarity_threshold=0.3, max_agents=3)

def supervisor(state: AgentState) -> Dict:
    """Supervisor that uses embeddings to decide which agent(s) to call next."""
    
    print("\n🔍 SUPERVISOR: Analyzing user message with embeddings...")
    
    # Get the last message from the conversation
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello, how can I help you?"
    
    print(f"📝 SUPERVISOR: User message: '{last_message}'")
    
    # Check if user wants to end conversation
    if any(word in last_message.lower() for word in ['quit', 'exit', 'bye', 'goodbye', 'end']):
        print("🛑 SUPERVISOR: User requested to end conversation")
        return {"supervisor_decision": END}
    
    # Use embedding-based multi-agent selection
    selected_agents = agent_selector.select_multiple_agents(last_message)
    
    print(f"✅ SUPERVISOR: Selected {len(selected_agents)} agent(s):")
    for i, agent_id in enumerate(selected_agents, 1):
        agent_info = AGENTS[agent_id]
        print(f"  {i}. {agent_info['name']}")
        print(f"     Specialization: {agent_info['description'][:80]}...")
    
    print(f"\n📊 Selection Summary:")
    print(f"   • Similarity threshold: {agent_selector.similarity_threshold}")
    print(f"   • Max agents allowed: {agent_selector.max_agents}")
    print(f"   • Agents selected: {len(selected_agents)}")
    if len(selected_agents) > 1:
        print(f"   • Mode: Multi-agent coordination")
    else:
        print(f"   • Mode: Single agent")
    
    # If multiple agents are selected, we'll use a special multi-agent node
    if len(selected_agents) > 1:
        # Store selected agents in the state and return the decision
        return {
            "supervisor_decision": "multi_agent",
            "selected_agents": selected_agents
        }
    else:
        # Single agent selection (backward compatibility)
        selected_agent = selected_agents[0]
        return {"supervisor_decision": selected_agent}

def general_conversation(state: AgentState) -> Command[Literal[END]]:
    """General conversation agent."""
    
    agent_info = AGENTS["general_conversation"]
    print(f"👤 {agent_info['name']}: Starting conversation...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 {agent_info['name']}: Processing message: '{last_message}'")
    
    system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

Be friendly, engaging, and helpful. Keep responses conversational and warm."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print(f"🤖 {agent_info['name']}: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print(f"✅ {agent_info['name']}: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ {agent_info['name']}: Error calling OpenAI API: {e}")
        return Command(goto=END)

def technical_support(state: AgentState) -> Command[Literal[END]]:
    """Technical support agent."""
    
    agent_info = AGENTS["technical_support"]
    print(f"💻 {agent_info['name']}: Starting technical support...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 {agent_info['name']}: Processing message: '{last_message}'")
    
    system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

Provide clear, practical technical solutions. Use simple language when explaining complex concepts."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print(f"🤖 {agent_info['name']}: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print(f"✅ {agent_info['name']}: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ {agent_info['name']}: Error calling OpenAI API: {e}")
        return Command(goto=END)

def creative_writing(state: AgentState) -> Command[Literal[END]]:
    """Creative writing agent."""
    
    agent_info = AGENTS["creative_writing"]
    print(f"✍️ {agent_info['name']}: Starting creative writing...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 {agent_info['name']}: Processing message: '{last_message}'")
    
    system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

Be creative, inspiring, and supportive of the user's creative journey."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print(f"🤖 {agent_info['name']}: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print(f"✅ {agent_info['name']}: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ {agent_info['name']}: Error calling OpenAI API: {e}")
        return Command(goto=END)

def business_consultant(state: AgentState) -> Command[Literal[END]]:
    """Business consultant agent."""
    
    agent_info = AGENTS["business_consultant"]
    print(f"💼 {agent_info['name']}: Starting business consultation...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 {agent_info['name']}: Processing message: '{last_message}'")
    
    system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

Provide practical business advice and strategic thinking. Be professional and insightful."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print(f"🤖 {agent_info['name']}: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print(f"✅ {agent_info['name']}: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ {agent_info['name']}: Error calling OpenAI API: {e}")
        return Command(goto=END)

def health_wellness(state: AgentState) -> Command[Literal[END]]:
    """Health and wellness agent."""
    
    agent_info = AGENTS["health_wellness"]
    print(f"🏥 {agent_info['name']}: Starting health consultation...")
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    print(f"📝 {agent_info['name']}: Processing message: '{last_message}'")
    
    system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

Provide helpful health and wellness advice. Be encouraging and supportive. Remember that you cannot provide medical diagnosis."""
    
    model_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=last_message)
    ]
    
    try:
        print(f"🤖 {agent_info['name']}: Calling OpenAI API...")
        response = model.invoke(model_messages)
        print(f"✅ {agent_info['name']}: Response generated successfully")
        
        return Command(
            goto=END,
            update={"messages": [response]},
        )
    except Exception as e:
        print(f"❌ {agent_info['name']}: Error calling OpenAI API: {e}")
        return Command(goto=END)

def multi_agent_handler(state: AgentState) -> Command[Literal[END]]:
    """Handle multiple agents for complex requests that require multiple specialties."""
    
    print("\n🤝 MULTI-AGENT: Coordinating multiple agents for comprehensive response...")
    print("=" * 80)
    
    messages = state["messages"]
    last_message = messages[-1].content if messages else "Hello!"
    
    # Get the selected agents from the state
    selected_agents = state.get("selected_agents", [])
    
    print(f"📝 MULTI-AGENT: Processing message: '{last_message}'")
    print(f"👥 MULTI-AGENT: Coordinating {len(selected_agents)} agents:")
    print()
    
    all_responses = []
    agent_outputs = {}
    
    for i, agent_id in enumerate(selected_agents, 1):
        agent_info = AGENTS[agent_id]
        print(f"🔄 AGENT {i}/{len(selected_agents)}: {agent_info['name']}")
        print(f"   📋 Specialization: {agent_info['description'][:100]}...")
        print(f"   🎯 Generating specialized response...")
        
        system_prompt = f"""You are {agent_info['name']}. {agent_info['description']}

You are part of a multi-agent team responding to a complex request. Provide your specialized perspective on this query. Be concise but thorough in your area of expertise."""
        
        model_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=last_message)
        ]
        
        try:
            response = model.invoke(model_messages)
            agent_outputs[agent_id] = response.content
            all_responses.append(f"**{agent_info['name']}:** {response.content}")
            
            print(f"   ✅ Response generated successfully")
            print(f"   📄 Response length: {len(response.content)} characters")
            print(f"   📝 Response preview: {response.content[:150]}...")
            print()
            
        except Exception as e:
            error_msg = f"**{agent_info['name']}:** Sorry, I encountered an error while processing your request."
            agent_outputs[agent_id] = error_msg
            all_responses.append(error_msg)
            print(f"   ❌ Error: {e}")
            print()
    
    # Combine all responses
    combined_response = "\n\n".join(all_responses)
    
    print("🔄 AGGREGATION PHASE:")
    print("=" * 50)
    print("📋 Individual Agent Responses:")
    for agent_id in selected_agents:
        agent_info = AGENTS[agent_id]
        response = agent_outputs[agent_id]
        print(f"\n🎯 {agent_info['name']}:")
        print(f"   {response}")
        print("-" * 40)
    
    print(f"\n📊 Aggregation Summary:")
    print(f"   • Total agents: {len(selected_agents)}")
    print(f"   • Total response length: {len(combined_response)} characters")
    print(f"   • Average response length: {len(combined_response) // len(selected_agents)} characters per agent")
    
    # Create a final coordination message
    coordination_prompt = f"""You are a coordination agent. The following responses have been generated by multiple specialized agents for a user query. 

User Query: "{last_message}"

Agent Responses:
{combined_response}

Please provide a cohesive, well-structured final response that synthesizes the different perspectives while maintaining clarity and avoiding redundancy. Make sure the response flows naturally and addresses the user's needs comprehensively."""
    
    print(f"\n🔄 FINAL COORDINATION:")
    print("=" * 50)
    print("🤖 Calling coordination agent to synthesize responses...")
    
    try:
        final_model_messages = [
            SystemMessage(content=coordination_prompt),
            HumanMessage(content=f"User query: {last_message}\n\nAgent responses:\n{combined_response}")
        ]
        
        final_response = model.invoke(final_model_messages)
        print("✅ Final coordinated response generated successfully")
        print(f"📄 Final response length: {len(final_response.content)} characters")
        print(f"📝 Final response preview: {final_response.content[:200]}...")
        
        # Show comparison with individual responses
        print(f"\n📊 Response Comparison:")
        print(f"   • Individual responses: {len(agent_outputs)}")
        print(f"   • Combined length: {len(combined_response)} characters")
        print(f"   • Final length: {len(final_response.content)} characters")
        print(f"   • Compression ratio: {len(final_response.content) / len(combined_response) * 100:.1f}%")
        print("=" * 80)
        
        return Command(
            goto=END,
            update={"messages": [final_response]},
        )
    except Exception as e:
        print(f"❌ MULTI-AGENT: Error in final coordination: {e}")
        print("🔄 Falling back to combined responses...")
        # Fallback to combined responses
        fallback_response = SystemMessage(content=combined_response)
        return Command(
            goto=END,
            update={"messages": [fallback_response]},
        )

# Build the graph
builder = StateGraph(AgentState)
builder.add_node("supervisor", supervisor)
builder.add_node("multi_agent_handler", multi_agent_handler)
builder.add_node("general_conversation", general_conversation)
builder.add_node("technical_support", technical_support)
builder.add_node("creative_writing", creative_writing)
builder.add_node("business_consultant", business_consultant)
builder.add_node("health_wellness", health_wellness)

# Add edges
builder.add_edge(START, "supervisor")
builder.add_conditional_edges(
    "supervisor",
    lambda x: x["supervisor_decision"],
    {
        "multi_agent": "multi_agent_handler",
        "general_conversation": "general_conversation",
        "technical_support": "technical_support", 
        "creative_writing": "creative_writing",
        "business_consultant": "business_consultant",
        "health_wellness": "health_wellness",
        END: END
    }
)
builder.add_edge("multi_agent_handler", END)
builder.add_edge("general_conversation", END)
builder.add_edge("technical_support", END)
builder.add_edge("creative_writing", END)
builder.add_edge("business_consultant", END)
builder.add_edge("health_wellness", END)

# Compile the graph
app = builder.compile()

if __name__ == "__main__":
    # Check if API key is set
    if not os.getenv("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable is not set.")
        print("Please set your OpenAI API key:")
        print("export OPENAI_API_KEY='your-api-key-here'")
        exit(1)
    
    # Example usage
    print("🤖 LangGraph Supervisor with Multi-Agent Embedding-Based Selection")
    print("Available agents:")
    for agent_id, agent_info in AGENTS.items():
        print(f"  • {agent_info['name']}")
    print("\n💡 Multi-agent capability:")
    print(f"  • Similarity threshold: {agent_selector.similarity_threshold}")
    print(f"  • Max agents per request: {agent_selector.max_agents}")
    print("  • Complex requests will automatically engage multiple agents")
    print("\n💬 Example multi-agent queries:")
    print("  • 'I want to start a tech business and need help with both business strategy and technical implementation'")
    print("  • 'I'm stressed about work and need both emotional support and career advice'")
    print("  • 'Help me write a creative story about a health-conscious entrepreneur'")
    print("\nType 'quit' to exit")
    print("-" * 50)
    
    # Initialize the conversation
    config = {"configurable": {"thread_id": "default"}}
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['quit', 'exit', 'bye']:
            print("Goodbye!")
            break
        
        # Run the graph with proper state initialization
        initial_state = {
            "messages": [HumanMessage(content=user_input)],
            "selected_agents": []
        }
        result = app.invoke(initial_state, config)
        
        # Get the last response
        if result["messages"]:
            last_response = result["messages"][-1].content
            print(f"Assistant: {last_response}")
        else:
            print("Assistant: I'm sorry, I couldn't process that request.")