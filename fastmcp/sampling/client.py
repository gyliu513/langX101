import asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.client.sampling import (
    SamplingMessage,
    SamplingParams,
    RequestContext,
)
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()


async def basic_sampling_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: RequestContext,
) -> str:
    # Use OpenAI to generate a response
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY not set in environment."

    client = AsyncOpenAI(api_key=api_key)

    # Build messages for OpenAI
    openai_messages = []
    system_prompt = getattr(params, "systemPrompt", None)
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    for m in messages:
        content_text = getattr(getattr(m, "content", None), "text", None)
        if content_text:
            openai_messages.append({"role": m.role, "content": content_text})

    completion = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=openai_messages or [{"role": "user", "content": "Say hello."}],
        temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.2")),
        max_tokens=int(os.getenv("OPENAI_MAX_TOKENS", "256")),
    )
    return completion.choices[0].message.content or ""


async def main():
    transport = StreamableHttpTransport(url="http://0.0.0.0:8000/mcp")
    async with Client(transport=transport, sampling_handler=basic_sampling_handler) as client:
        tools = await client.list_tools()
        print(tools)
        if any(t.name == "summarize" for t in tools):
            result = await client.call_tool(
                "summarize",
                {"text": "FastMCP allows servers to ask clients to perform LLM sampling, enabling tools to delegate text generation to the user's selected model while preserving client-side controls like API keys, model choice, safety settings, rate limits, and observability hooks so we can run a realistic end-to-end test of sampling behavior across a longer, more descriptive sentence that better exercises token handling and truncation logic in both the client and the server."},
            )
            print(f"summarize -> {result}")
        else:
            print("summarize tool not found. Available:", [t.name for t in tools])


if __name__ == "__main__":
    asyncio.run(main())


