from langchain.schema import SystemMessage, HumanMessage
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnableMap
from langserve import RemoteRunnable
import asyncio

openai = RemoteRunnable("http://localhost:8000/openai/")
anthropic = RemoteRunnable("http://localhost:8000/anthropic/")
joke_chain = RemoteRunnable("http://localhost:8000/chain/")

# Synchronous invocation
result = joke_chain.invoke({"topic": "parrots"})
print("Synchronous result:", result)

# Async function for async operations
async def run_async_operations():
    # Async invocation
    async_result = await joke_chain.ainvoke({"topic": "parrots"})
    print("Async result:", async_result)
    
    # Supports astream
    print("\nStreaming response:")
    async for msg in anthropic.astream([
        SystemMessage(content='Act like either a cat or a parrot.'),
        HumanMessage(content='Hello!')
    ]):
        print(msg, end="", flush=True)
    print("\n")

# Define custom chains
prompt = ChatPromptTemplate.from_messages(
    [("system", "Tell me a long story about {topic}")]
)

chain = prompt | RunnableMap({
    "openai": openai,
    "anthropic": anthropic,
})

# Batch processing
batch_results = chain.batch([{ "topic": "parrots" }, { "topic": "cats" }])
print("Batch results:", batch_results)

# Run async operations if this script is executed directly
if __name__ == "__main__":
    asyncio.run(run_async_operations())
