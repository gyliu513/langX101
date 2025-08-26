# LangGraph Agentic Workflow Implementation

This project demonstrates the **agentic workflow** pattern using LangGraph, implementing the complete workflow with planning, execution, reflection, and decision-making phases.

## 🎯 What is the Agentic Workflow?

The agentic workflow consists of four main phases:

1. **Planning Phase**: An LLM creates a detailed, step-by-step plan to solve a problem
2. **Execution Phase**: The plan is executed step by step using available tools
3. **Reflection Phase**: Results are evaluated to determine if they meet requirements
4. **Decision Phase**: Either continue with next steps or replan if results are not satisfactory

### Key Benefits

- ✅ Better task decomposition and reasoning
- ✅ Ability to handle complex, multi-step problems  
- ✅ Dynamic replanning when execution fails
- ✅ Continuous reflection and improvement
- ✅ More reliable and interpretable results
- ✅ Clear separation of concerns between planning and execution

## 🚀 Quick Start

### Prerequisites

- Python 3.9 or higher
- `uv` package manager installed
- Google API key for Gemini model access

### Installation

1. **Clone or navigate to this directory:**
   ```bash
   cd langgraph/plan-and-execute
   ```

2. **Install dependencies using uv:**
   ```bash
   uv sync
   ```

3. **Set up your environment variables:**
   Create a `.env` file in the project directory:
   ```bash
   echo "GOOGLE_API_KEY=your_google_api_key_here" > .env
   echo "TAVILY_API_KEY=your_tavily_api_key_here" >> .env  # Optional for search functionality
   ```

### Running the Demo

```bash
uv run plan_and_execute.py
```

## 📁 Project Structure

```
plan-and-execute/
├── plan_and_execute.py    # Main implementation file
├── pyproject.toml         # Project dependencies and configuration
├── README.md              # This file
└── .env                   # Environment variables (create this)
```

## 🔧 How It Works

### 1. State Management
The `AgentState` class maintains the workflow state:
- **messages**: Conversation history
- **plan**: Current execution plan
- **current_step**: Current step being executed
- **results**: Results from executed steps
- **replan_count**: Number of replanning attempts

### 2. Workflow Nodes

#### Planner Node (`planner_node`)
- Creates detailed, step-by-step plans
- Breaks down complex problems into manageable tasks
- Considers dependencies and research needs

#### Executor Node (`executor_node`)
- Executes individual plan steps
- Uses tools when appropriate (e.g., search for research)
- Tracks execution results

#### Replanner Node (`replanner_node`)
- Creates new plans when execution fails
- Builds on successful steps
- Addresses identified issues

### 3. Graph Flow

```
Planner → Executor → Should Continue? → Next Step or End
   ↑         ↓
Replanner ← Failure
```

## 🛠️ Customization

### Changing the LLM Model

Edit the `llm` configuration in `plan_and_execute.py`:

```python
llm = ChatGoogleGenerativeAI(
    model="gemini-1.5-flash",  # Change to your preferred model
    google_api_key=api_key,
    temperature=0
)
```

### Adding Custom Tools

Extend the tools list with your own tools:

```python
from your_module import YourCustomTool

tools = [search_tool, YourCustomTool()]
tool_executor = ToolExecutor(tools)
```

### Modifying Prompts

Customize the prompt templates to match your use case:

```python
PLANNER_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "Your custom system prompt here..."),
    MessagesPlaceholder(variable_name="messages"),
    ("human", "Your custom human prompt: {input}"),
])
```

## 📊 Example Output

When you run the script, you'll see output like:

```
🚀 LangGraph Agentic Workflow Demo
==================================================
🎯 Problem: what is the hometown of the current Australia open winner?...

🤔 Planning phase...
📋 Generated plan:
1. Research popular tourist attractions in San Francisco
2. Find local food recommendations within budget
3. Plan cultural activities and experiences
4. Create a 2-day itinerary with timing
5. Calculate total estimated costs

⚡ Executing step 1...
📝 Executing: 1. Research popular tourist attractions in San Francisco
✅ Step 1 completed: Research completed: Found Golden Gate Bridge, Alcatraz...

🔄 Moving to step 2
⚡ Executing step 2...
...
```

## 🔍 Troubleshooting

### Common Issues

1. **API Key Not Found**
   - Ensure your `.env` file exists and contains `GOOGLE_API_KEY`
   - Check that the file is in the correct directory

2. **Import Errors**
   - Run `uv sync` to install all dependencies
   - Verify Python version is 3.9+

3. **Rate Limiting**
   - The script automatically selects the best available model
   - If one model has rate limits, try another provider
   - Consider using local Ollama models for unlimited usage

4. **Search Tool Issues**
   - Tavily search requires an API key (optional)
   - Remove search functionality if not needed

### Debug Mode

Add debug prints by modifying the node functions or add logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🧪 Testing Different Problems

Modify the `problem` variable in the `main()` function to test different scenarios:

```python
problem = """
Your custom problem description here. Make it complex enough to require multiple steps.
"""
```

## 📚 Learn More

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Documentation](https://python.langchain.com/)
- [Plan-and-Execute Pattern](https://arxiv.org/abs/2303.03378)

## 🤝 Contributing

Feel free to:
- Add new tools and capabilities
- Improve error handling and robustness
- Enhance the prompt templates
- Add more examples and use cases

## 📄 License

This project is based on the LangGraph tutorial and is provided for educational purposes.
