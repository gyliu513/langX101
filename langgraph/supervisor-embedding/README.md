# LangGraph Supervisor with Embedding-Based Agent Selection

This project demonstrates a sophisticated multi-agent system using LangGraph where a supervisor uses **embeddings** to intelligently route user queries to the most appropriate specialized agent.

## 🚀 Key Features

- **Embedding-Based Routing**: Uses OpenAI embeddings to find the most semantically similar agent for each user query
- **5 Specialized Agents**: Each agent has detailed descriptions and examples of their capabilities
- **Cosine Similarity**: Calculates similarity scores between user queries and agent descriptions
- **Transparent Selection**: Shows similarity scores for all agents during selection
- **Detailed Agent Profiles**: Each agent has comprehensive descriptions and example queries

## 🤖 Available Agents

### 1. General Conversation Agent 👤
- **Specializes in**: Casual conversations, emotional support, general advice
- **Examples**: "How are you today?", "Tell me a joke", "I'm feeling stressed"

### 2. Technical Support Agent 💻
- **Specializes in**: Programming, debugging, technical troubleshooting
- **Examples**: "How do I fix this Python error?", "My computer is running slow"

### 3. Creative Writing Agent ✍️
- **Specializes in**: Storytelling, poetry, creative inspiration
- **Examples**: "Help me write a story", "Write a poem about love"

### 4. Business Consultant Agent 💼
- **Specializes in**: Business strategy, entrepreneurship, career advice
- **Examples**: "How do I start a business?", "Help me create a business plan"

### 5. Health & Wellness Agent 🏥
- **Specializes in**: Fitness, nutrition, wellness, healthy living
- **Examples**: "How can I improve my fitness?", "What should I eat for breakfast?"

## 🔧 How It Works

### 1. Agent Initialization
- Each agent has a detailed description including their capabilities and example queries
- Embeddings are created for each agent's full description during startup
- These embeddings capture the semantic meaning of what each agent can handle

### 2. Query Processing
- When a user sends a message, an embedding is created for the user's query
- Cosine similarity is calculated between the user's query and each agent's description
- The agent with the highest similarity score is selected

### 3. Agent Selection
- The system shows similarity scores for all agents (for transparency)
- The most appropriate agent is automatically routed to handle the query
- Each agent has its own specialized system prompt based on its description

## 📊 Example Selection Process

```
🔍 SUPERVISOR: Analyzing user message with embeddings...
📝 SUPERVISOR: User message: 'How do I fix this Python error?'
🔍 Agent selection results:
  Technical Support Agent: 0.892
  General Conversation Agent: 0.234
  Creative Writing Agent: 0.156
  Business Consultant Agent: 0.123
  Health & Wellness Agent: 0.089
✅ SUPERVISOR: Selected Technical Support Agent
```

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd langgraph/supervisor-embedding
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Set up environment variables**:
   ```bash
   export OPENAI_API_KEY='your-openai-api-key-here'
   ```

## 🚀 Usage

Run the application:
```bash
uv run main.py
```

### Example Interactions

**Technical Query:**
```
You: How do I debug this Python code?
🔍 SUPERVISOR: Selected Technical Support Agent
💻 Technical Support Agent: I can help you debug your Python code...
```

**Creative Query:**
```
You: Help me write a poem about nature
🔍 SUPERVISOR: Selected Creative Writing Agent
✍️ Creative Writing Agent: Let me help you create a beautiful poem...
```

**Business Query:**
```
You: How do I create a marketing strategy?
🔍 SUPERVISOR: Selected Business Consultant Agent
💼 Business Consultant Agent: Here's how to develop an effective marketing strategy...
```

## 🏗️ Architecture

### Core Components

1. **AgentSelector Class**
   - Manages agent embeddings
   - Calculates cosine similarity
   - Selects the most appropriate agent

2. **AGENTS Dictionary**
   - Contains detailed descriptions for each agent
   - Includes examples and capabilities
   - Used to create embeddings

3. **LangGraph Workflow**
   - Supervisor node for routing
   - Individual agent nodes for processing
   - State management with MessagesState

### Embedding Process

```python
# Agent description embedding
agent_description = f"{agent_name}: {agent_description} {examples}"
agent_embedding = embeddings.embed_query(agent_description)

# User query embedding
user_embedding = embeddings.embed_query(user_message)

# Similarity calculation
similarity = cosine_similarity(user_embedding, agent_embedding)
```

## 🎯 Advantages of Embedding-Based Selection

1. **Semantic Understanding**: Captures meaning beyond keyword matching
2. **Flexible Matching**: Can handle variations in how users phrase queries
3. **Scalable**: Easy to add new agents with descriptions
4. **Transparent**: Shows similarity scores for debugging
5. **Accurate**: More precise than rule-based routing

## 🔍 Customization

### Adding New Agents

To add a new agent, simply add it to the `AGENTS` dictionary:

```python
AGENTS["new_agent"] = {
    "name": "New Agent Name",
    "description": "Detailed description of capabilities...",
    "examples": [
        "Example query 1",
        "Example query 2"
    ]
}
```

### Modifying Agent Descriptions

Update the description and examples in the `AGENTS` dictionary to improve routing accuracy.

### Adjusting Similarity Thresholds

You can add minimum similarity thresholds to ensure only high-confidence matches are routed to specific agents.

## 📈 Performance Considerations

- **Embedding Cost**: Each query requires 2 API calls (user query + agent selection)
- **Latency**: Embedding generation adds some latency to the response
- **Caching**: Consider caching agent embeddings for production use
- **Batch Processing**: For high-volume scenarios, consider batch embedding operations

## 🤝 Contributing

Feel free to:
- Add new specialized agents
- Improve agent descriptions
- Optimize the similarity calculation
- Add more sophisticated routing logic

## 📄 License

This project is open source and available under the MIT License. 