# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from llama_stack_client import Agent, AgentEventLogger, LlamaStackClient
import requests
from io import BytesIO

vector_store_id = "my_demo_vector_db"
client = LlamaStackClient(base_url="http://localhost:8321")

models = client.models.list()

# Select the first LLM model
model_id = next(m for m in models if m.model_type == "llm").identifier

# Create vector store using file-based approach
source = "https://www.paulgraham.com/greatwork.html"
print("rag_tool> Ingesting document:", source)
response = requests.get(source)

# Create a file-like object from the HTML content
file_buffer = BytesIO(response.content)
file_buffer.name = "greatwork.html"

file = client.files.create(
    file=file_buffer,
    purpose='assistants'
)
print(f"✓ File created with ID: {file.id}")

vector_store = client.vector_stores.create(
    name=vector_store_id,
    file_ids=[file.id],
)
print(f"✓ Vector store created with ID: {vector_store.id}")

agent = Agent(
    client,
    model=model_id,
    instructions="You are a helpful assistant",
    tools=[
        {
            "type": "file_search",
            "vector_store_ids": [vector_store.id],
        }
    ],
)

prompt = "How do you do great work?"
print("prompt>", prompt)

use_stream = True
response = agent.create_turn(
    messages=[{"role": "user", "content": prompt}],
    session_id=agent.create_session("rag_session"),
    stream=use_stream,
)

# Only call `AgentEventLogger().log(response)` for streaming responses.
if use_stream:
    for log in AgentEventLogger().log(response):
        print(log, end="")
else:
    print(response)