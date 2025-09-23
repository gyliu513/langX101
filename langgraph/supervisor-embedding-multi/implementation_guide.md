# Implementation Guide: Fixing the Build Error

## Problem

The current project structure is causing a build error with the following message:

```
error: Multiple top-level modules discovered in a flat-layout: ['test_multi_agent', 'main'].
```

This error occurs because setuptools is finding multiple Python modules at the top level of the package (`test_multi_agent.py` and `main.py`), and it doesn't know which one should be the main module for the package.

## Solution

We'll implement a `src-layout` structure, which is a common Python packaging practice that clearly separates the package code from other project files.

## Implementation Steps

### 1. Create the src-layout directory structure

Create the following directory structure:

```
langgraph/supervisor-embedding-multi/
├── pyproject.toml (updated)
├── README.md
├── src/
│   └── langgraph_supervisor/
│       ├── __init__.py (new file)
│       ├── main.py (moved from root)
│       └── test_multi_agent.py (moved from root)
```

### 2. Create the __init__.py file

Create a new `__init__.py` file in the `src/langgraph_supervisor` directory with the following content:

```python
"""LangGraph supervisor package with embedding-based multi-agent selection."""

from .main import app, AGENTS, agent_selector

__all__ = ["app", "AGENTS", "agent_selector"]
```

### 3. Move and update the Python modules

1. Move `main.py` to `src/langgraph_supervisor/main.py` without changes to its content.

2. Move `test_multi_agent.py` to `src/langgraph_supervisor/test_multi_agent.py` and update the import statement:

```python
# Change this line:
from main import agent_selector, AGENTS

# To this:
from langgraph_supervisor.main import agent_selector, AGENTS
```

### 4. Update pyproject.toml

Update the `pyproject.toml` file to use the src-layout:

```toml
[project]
name = "langgraph-supervisor"
version = "0.1.0"
description = "LangGraph supervisor example with OpenAI API"
requires-python = ">=3.9"
dependencies = [
    "langgraph>=0.2.0",
    "langchain>=0.2.0",
    "langchain-openai>=0.2.0",
    "python-dotenv>=1.0.0",
    "numpy>=1.24.0",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools]
package-dir = {"" = "src"}

[tool.uv]
dev-dependencies = []
```

### 5. Test the build

After implementing all the changes, run the following command from the `langgraph/supervisor-embedding-multi` directory:

```bash
uv run -m langgraph_supervisor.test_multi_agent
```

To run the main application:

```bash
uv run -m langgraph_supervisor.main
```

To install the package in development mode:

```bash
uv pip install -e .
```

## Benefits of src-layout

1. **Clear separation**: Separates your package code from project files
2. **Prevents import confusion**: Ensures you're using the installed package during development
3. **Standard practice**: Follows Python packaging best practices
4. **Easier testing**: Makes it clearer how to import your package for testing

## Additional Resources

- [Python Packaging User Guide](https://packaging.python.org/en/latest/tutorials/packaging-projects/)
- [Setuptools Documentation](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html)