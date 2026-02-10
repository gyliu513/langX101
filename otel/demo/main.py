
from openai import OpenAI
import os
import requests

def main():

    github_token = os.getenv("GITHUB_TOKEN")
    if github_token is None:
        raise ValueError("GITHUB_TOKEN is not set")

    client = OpenAI(
        api_key="fake",
        base_url="http://localhost:8321/v1/",
    )

    response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello, how are you?"}]
    )
    print("Sync response: ", response.choices[0].message.content)

    streaming_response = client.chat.completions.create(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        stream=True,
        stream_options={"include_usage": True}
    )

    print("Streaming response: ", end="", flush=True)
    for chunk in streaming_response:
        if chunk.usage is not None:
            print("Usage: ", chunk.usage)
        if chunk.choices and chunk.choices[0].delta is not None:
            print(chunk.choices[0].delta.content, end="", flush=True)
    print()

    ollama_response = client.chat.completions.create(
        model="ollama/llama3.2:3b-instruct-fp16",
        messages=[{"role": "user", "content": "How are you doing today?"}]
    )
    print("Ollama response: ", ollama_response.choices[0].message.content)

    # Try the original MCP URL that was working
    mcp_server_url = "https://api.githubcopilot.com/mcp/x/repos/readonly"
    mcp_auth = github_token  # Just the token, no "Bearer " prefix

    try:
        responses_list_tools_response = client.responses.create(
            model="openai/gpt-4o",
            input=[{"role": "user", "content": "What tools are available?"}],
            tools=[
                {
                    "type": "mcp",
                    "server_label": "github",
                    "server_url": mcp_server_url,
                    "authorization": mcp_auth,
                }
            ],
        )
        print("Responses list tools response: ", responses_list_tools_response.output_text)
    except Exception as e:
        print(f"MCP list tools error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    try:
        responses_tool_call_response = client.responses.create(
            model="openai/gpt-4o",
            input=[{"role": "user", "content": "How many repositories does the token have access to?"}],
            tools=[
                {
                    "type": "mcp",
                    "server_label": "github",
                    "server_url": mcp_server_url,
                    "authorization": mcp_auth,
                }
            ],
        )
        print("Responses tool call response: ", responses_tool_call_response.output_text)
    except Exception as e:
        print(f"MCP tool call error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()
