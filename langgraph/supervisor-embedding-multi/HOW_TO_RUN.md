# How to Run with UV

After restructuring the project to use a src-layout, here's how to run the code using `uv run`:

## Running the Test Script

```bash
# Navigate to the package directory
cd langgraph/supervisor-embedding-multi

# Run the test script
uv run -m langgraph_supervisor.test_multi_agent
```

## Running the Main Application

```bash
# Navigate to the package directory
cd langgraph/supervisor-embedding-multi

# Run the main application
uv run -m langgraph_supervisor.main
```

## Using the Run Scripts

You can also use the provided run scripts with `uv run`:

```bash
# Run the test script
uv run run_test.py

# Run the main application
uv run run_app.py
```

## Troubleshooting

If you encounter any issues, make sure:

1. Your OPENAI_API_KEY environment variable is set
2. You're running the commands from the correct directory
3. All dependencies are installed

For more details on the implementation, please refer to the implementation_guide.md file.