# Math Agent

Advanced mathematical assistant for calculations, equation solving, calculus, statistics, and matrix operations using **Google AI (Gemini 1.5 Flash)**, **MCP (Model Context Protocol)**, and **A2A SDK**.

## 🏗️ Architecture Overview

The Math Agent uses a sophisticated **MCP-based architecture** that separates mathematical computation from language understanding:

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────────┐
│   User Query    │───▶│   Math Agent     │───▶│   MCP Math Server   │
│ "What is 2+3?"  │    │ (LLM + MCP Client)    │ (SymPy + NumPy)     │
└─────────────────┘    └──────────────────┘    └─────────────────────┘
                              │                           │
                              ▼                           ▼
                       ┌──────────────────┐    ┌─────────────────────┐
                       │  A2A Protocol    │    │  Mathematical Tools │
                       │   Integration    │    │ • calculate_expression
                       └──────────────────┘    │ • solve_equation    │
                                               │ • derivative        │
                                               │ • integral          │
                                               │ • matrix_operations │
                                               │ • statistics_calculator
                                               └─────────────────────┘
```

## Features

### 🧮 Arithmetic Calculations
- Basic operations: addition, subtraction, multiplication, division
- Advanced functions: trigonometric, logarithmic, exponential
- Mathematical constants: π, e, etc.

### 📐 Equation Solving
- Linear equations: `2x + 5 = 11`
- Quadratic equations: `x^2 - 4 = 0`
- Polynomial equations of any degree
- Systems of equations

### 📊 Calculus Operations
- **Derivatives**: Find derivatives of mathematical functions
- **Integrals**: Calculate indefinite integrals
- Support for symbolic mathematics

### 🔢 Matrix Operations
- Matrix multiplication, addition, subtraction
- Matrix inverse and transpose
- Determinant calculation
- Support for any size matrices

### 📈 Statistics Analysis
- Descriptive statistics: mean, median, mode
- Variability measures: standard deviation, variance
- Data analysis for numerical datasets

## Installation

```bash
cd mathAgent
pip install -e .
```

## Environment Setup

Create a `.env` file in the mathAgent directory:

```env
# Google AI API Key (required)
GOOGLE_API_KEY=your_google_api_key_here

# Optional: Model source (defaults to "google")
model_source=google

# Optional: Port (defaults to 8003)
PORT=8003
```

## Usage

### Starting the Agent

```bash
cd mathAgent
python -m app
```

The agent will start on `http://localhost:8003` by default.

### Example Queries

#### Arithmetic Calculations
```
"Calculate 2 + 2"
"What is the square root of 16?"
"What is sin(pi/4)?"
"Calculate log(100)"
```

#### Equation Solving
```
"Solve x^2 - 4 = 0"
"Solve 2x + 5 = 11"
"Find the roots of x^3 - 6x^2 + 11x - 6 = 0"
```

#### Calculus
```
"Find the derivative of x^2 + 3x + 2"
"Calculate the integral of x^2"
"What is the derivative of sin(x)?"
"Integrate e^x dx"
```

#### Matrix Operations
```
"What is the determinant of [[1,2],[3,4]]?"
"Multiply matrices [[1,2],[3,4]] and [[5,6],[7,8]]"
"Find the inverse of [[2,1],[1,1]]"
"Transpose [[1,2,3],[4,5,6]]"
```

#### Statistics
```
"Find the mean of [1,2,3,4,5]"
"Calculate the standard deviation of [10,12,14,16,18]"
"What is the median of [1,3,5,7,9,11]?"
"Find the variance of [2,4,6,8,10]"
```

## 🧪 Comprehensive Testing Suite

The Math Agent includes **8 comprehensive test files** covering all aspects of functionality:

### 📋 Test Files Overview

- **[Test Documentation](test/README.md)** - Complete testing guide
- **`simple_test.py`** - Basic functionality test
- **`comprehensive_test.py`** - Full MCP + LLM integration test  
- **`test_mcp_connection.py`** - MCP server connection test
- **`test_mcp_agent.py`** - All 6 MCP mathematical tools test
- **`test_math_functions.py`** - Direct mathematical operations test
- **`test_orchestrator_routing.py`** - Orchestrator routing test
- **`debug_routing.py`** - Routing decision debugging

### 🚀 Quick Testing

```bash
# Basic functionality test
cd mathAgent
uv run python test/simple_test.py

# Comprehensive MCP + LLM test
uv run python test/comprehensive_test.py

# Test all MCP tools individually
uv run python test/test_mcp_agent.py

# Test orchestrator routing for math queries
uv run python test/test_orchestrator_routing.py
```

### 🔍 Expected Test Results

**Simple Test**:
```
🔢 Testing: What is 5 + 7?
📊 Result: 12
```

**Comprehensive Test**:
```
1. 🔢 Question: What is (3 + 5) × 12?
   📊 Answer: (3 + 5) × 12 = 96

2. 🔢 Question: Solve the equation 2x + 5 = 15
   📊 Answer: x = 5
```

## A2A SDK Integration

The Math Agent implements the A2A SDK protocol with:

- **Agent Card**: Describes capabilities and skills
- **Message Handling**: Processes mathematical queries
- **Streaming Support**: Real-time response streaming
- **Task Management**: Proper task state handling

### Agent Skills

1. **Arithmetic Calculation**: Basic and advanced mathematical operations
2. **Equation Solving**: Algebraic equation resolution
3. **Calculus Operations**: Derivatives and integrals
4. **Matrix Operations**: Linear algebra computations
5. **Statistics Analysis**: Data analysis and statistical measures

## MCP Tools Available

The agent connects to a Math MCP server that provides these mathematical tools:

- `calculate_expression`: Safe evaluation of mathematical expressions using SymPy
- `solve_equation`: Algebraic equation solver using SymPy
- `derivative`: Calculus derivative calculator using SymPy
- `integral`: Calculus integral calculator using SymPy
- `matrix_operations`: Linear algebra operations using NumPy
- `statistics_calculator`: Statistical analysis functions using NumPy

## Dependencies

- **A2A SDK**: Agent-to-Agent communication protocol
- **MCP (Model Context Protocol)**: Tool communication protocol
- **Google AI (Gemini)**: Large language model for mathematical reasoning
- **SymPy**: Symbolic mathematics library (via MCP server)
- **NumPy**: Numerical computing library (via MCP server)
- **LangChain**: LLM application framework
- **LangGraph**: Workflow orchestration

## Architecture

```
Math Agent
├── Agent Core (agent.py)
│   ├── MCP Client Integration
│   ├── Google AI Integration
│   └── Response Formatting
├── Agent Executor (agent_executor.py)
│   ├── A2A SDK Integration
│   ├── Message Processing
│   └── Task Management
├── MCP Server (math_mcp_server.py)
│   ├── Mathematical Tools
│   ├── SymPy Integration
│   └── NumPy Integration
└── Server (__main__.py)
    ├── Agent Card Definition
    ├── HTTP Server
    └── Endpoint Configuration
```

## Error Handling

The agent handles various error scenarios:

- Invalid mathematical expressions
- Unsupported operations
- Matrix dimension mismatches
- Division by zero
- Complex number results
- Timeout scenarios

## Performance

- **Response Time**: Typically 1-3 seconds for simple calculations
- **Complex Operations**: 3-10 seconds for advanced calculus/matrix operations
- **Streaming**: Real-time progress updates for long calculations
- **Memory**: Conversation context maintained per session

## Troubleshooting

### Common Issues

1. **Agent won't start**: Check Google API key in environment
2. **Calculation errors**: Verify mathematical expression syntax
3. **Matrix errors**: Ensure proper matrix format `[[1,2],[3,4]]`
4. **Timeout issues**: Complex calculations may take longer

### Debugging

Enable debug logging:
```bash
export LOG_LEVEL=debug
python -m app
```

## Contributing

To extend the Math Agent:

1. Add new tools in `agent.py`
2. Update agent skills in `__main__.py`
3. Add test cases in `test_client.py`
4. Update documentation

## License

MIT License - see LICENSE file for details. 