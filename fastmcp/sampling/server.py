import asyncio
from fastmcp import FastMCP, Context


mcp = FastMCP("SamplingDemo")


@mcp.tool
async def summarize(text: str, ctx: Context) -> str:
    """Ask the client's LLM to summarize the given text in one sentence."""
    prompt = (
        "Summarize the following text in one concise sentence.\n\n" + text
    )
    response = await ctx.sample(prompt)
    return getattr(response, "text", str(response))


async def main():
    print("Starting FastMCP sampling server on http://0.0.0.0:8000/mcp")
    await mcp.run_http_async(transport="streamable-http")


if __name__ == "__main__":
    asyncio.run(main())


