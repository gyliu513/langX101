# LangGraph Supervisor with Multi-Agent Embedding-Based Selection

This project demonstrates a sophisticated **multi-agent system** using LangGraph where a supervisor uses **embeddings** to intelligently route user queries to one or multiple specialized agents based on the complexity and scope of the request.

## 🚀 Key Features

- **Multi-Agent Coordination**: Automatically selects and coordinates multiple agents for complex requests
- **Embedding-Based Routing**: Uses OpenAI embeddings to find semantically similar agents
- **Intelligent Threshold Selection**: Configurable similarity thresholds for multi-agent selection
- **Comprehensive Logging**: Detailed logging of agent selection, individual responses, and aggregation
- **5 Specialized Agents**: Each agent has detailed descriptions and examples of their capabilities
- **Response Synthesis**: Coordinates multiple agent responses into cohesive final answers
- **Cosine Similarity**: Calculates similarity scores between user queries and agent descriptions

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

### 1. Multi-Agent Selection
- **Similarity Threshold**: Configurable threshold (default: 0.3) to determine which agents are selected
- **Max Agents**: Configurable limit (default: 3) on how many agents can be selected
- **Intelligent Routing**: Automatically detects when multiple agents are needed for complex requests

### 2. Agent Coordination Process
1. **Query Analysis**: User message is analyzed using embeddings
2. **Multi-Agent Selection**: All agents above similarity threshold are selected
3. **Parallel Processing**: Each selected agent generates their specialized response
4. **Response Aggregation**: Individual responses are collected and analyzed
5. **Final Synthesis**: A coordination agent synthesizes all responses into a cohesive answer

### 3. Enhanced Logging
- **Selection Process**: Shows similarity scores and selection criteria
- **Individual Responses**: Displays each agent's complete response
- **Aggregation Statistics**: Shows response lengths and compression ratios
- **Final Coordination**: Tracks the synthesis process

## 📊 Example Multi-Agent Process

```
🔍 SUPERVISOR: Analyzing user message with embeddings...
📊 Similarity Analysis:
     Creative Writing Agent: 0.808 ≥ 0.300 ✅ SELECTED
     Health & Wellness Agent: 0.806 ≥ 0.300 ✅ SELECTED
     Business Consultant Agent: 0.797 ≥ 0.300 ✅ SELECTED
     General Conversation Agent: 0.764 < 0.300 ❌ NOT SELECTED

🔄 AGENT 1/3: Creative Writing Agent
   ✅ Response generated successfully
   📄 Response length: 245 characters

🔄 AGENT 2/3: Health & Wellness Agent
   ✅ Response generated successfully
   📄 Response length: 312 characters

🔄 AGGREGATION PHASE:
📋 Individual Agent Responses:
🎯 Creative Writing Agent: [Full response content]
🎯 Health & Wellness Agent: [Full response content]

🔄 FINAL COORDINATION:
📊 Response Comparison:
   • Individual responses: 3
   • Combined length: 1,200 characters
   • Final length: 800 characters
   • Compression ratio: 66.7%
```

## 🛠️ Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd langgraph/supervisor-embedding-multi
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

### Example Multi-Agent Interactions

**Complex Business + Technical Query:**
```
You: I want to start a tech business and need help with both business strategy and technical implementation
🔍 SUPERVISOR: Selected 3 agent(s):
  1. Business Consultant Agent
  2. Technical Support Agent
  3. General Conversation Agent
🤝 MULTI-AGENT: Coordinating multiple agents for comprehensive response...
```

**Health + Creative Query:**
```
You: Help me write a creative story about a health-conscious entrepreneur
🔍 SUPERVISOR: Selected 3 agent(s):
  1. Creative Writing Agent
  2. Health & Wellness Agent
  3. Business Consultant Agent
```

**Emotional + Career Support:**
```
You: I'm stressed about work and need both emotional support and career advice
🔍 SUPERVISOR: Selected 3 agent(s):
  1. Business Consultant Agent
  2. Health & Wellness Agent
  3. General Conversation Agent
```

## 🏗️ Architecture

### Core Components

1. **AgentSelector Class**
   - Manages agent embeddings
   - Calculates cosine similarity
   - Supports both single and multi-agent selection
   - Configurable thresholds and limits

2. **Multi-Agent Handler**
   - Coordinates multiple agents
   - Collects individual responses
   - Synthesizes final coordinated response
   - Provides comprehensive logging

3. **Custom State Management**
   - `AgentState` with `messages` and `selected_agents`
   - Preserves selected agents through graph transitions
   - Enables multi-agent coordination

### Configuration Options

```python
# Initialize with custom thresholds
agent_selector = AgentSelector(
    similarity_threshold=0.3,  # Minimum similarity to select agent
    max_agents=3               # Maximum agents per request
)
```

## 🎯 Multi-Agent Advantages

1. **Comprehensive Responses**: Multiple perspectives on complex queries
2. **Specialized Expertise**: Each agent contributes their unique knowledge
3. **Intelligent Coordination**: Automatic synthesis of multiple responses
4. **Scalable Architecture**: Easy to add new agents and specialties
5. **Transparent Process**: Full visibility into selection and coordination

## 🔍 Customization

### Adjusting Multi-Agent Parameters

```python
# More selective (fewer multi-agent responses)
agent_selector = AgentSelector(similarity_threshold=0.5, max_agents=2)

# More inclusive (more multi-agent responses)
agent_selector = AgentSelector(similarity_threshold=0.2, max_agents=4)
```

### Adding New Agents

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

### Customizing Logging

The system provides detailed logging at each stage:
- **Selection Process**: Similarity scores and criteria
- **Individual Processing**: Agent responses and statistics
- **Aggregation**: Combined responses and metrics
- **Final Coordination**: Synthesis process and results

## 📈 Performance Considerations

- **API Calls**: Each multi-agent request requires multiple API calls
- **Response Time**: Multi-agent requests take longer due to coordination
- **Cost Management**: Consider rate limiting and caching for production
- **Quality vs Speed**: Balance between comprehensive responses and response time

## 🧪 Testing

Run the test script to verify multi-agent functionality:
```bash
uv run test_multi_agent.py
```

This will test various queries and show how the system selects multiple agents.

## 🤝 Contributing

Feel free to:
- Add new specialized agents
- Improve agent descriptions and examples
- Optimize similarity thresholds
- Enhance the coordination logic
- Add more sophisticated aggregation strategies

## 📄 License

This project is open source and available under the MIT License. 