from openai import OpenAI
import os

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", "fake"),
    base_url="http://localhost:8321/v1/",
)

def main():
    resp = client.responses.create(
        model="openai/gpt-4o",
        input=[{"role": "user", "content": "Please call add(1, 1) and return the result"}],
        tools=[
            {
                "type": "mcp",
                "server_label": "plus-tools",
                "server_url": "http://localhost:8000/sse",
                # "authorization": "Bearer <token>"
            }
        ],
        tool_choice="auto",
    )
    print("Final answer:\n", resp.output_text)

if __name__ == "__main__":
    main()
