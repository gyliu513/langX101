# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

"""
Demo script showing RAG with both Responses API and Chat Completions API.

This example demonstrates two approaches to RAG with Llama Stack:
1. Responses API - Automatic agentic tool calling with file search
2. Chat Completions API - Manual retrieval with explicit control

Run this script after starting a Llama Stack server:
    llama stack run starter
"""

import io
import os

import requests
from openai import OpenAI

# Initialize OpenAI client pointing to Llama Stack server
client = OpenAI(base_url="http://localhost:8321/v1/", api_key="none")

print("RAG demonstration\n")

url = "https://www.paulgraham.com/greatwork.html"
print(f"Fetching document from: {url}")

vs = client.vector_stores.create()

response = requests.get(url)
pseudo_file = io.BytesIO(str(response.content).encode("utf-8"))
uploaded_file = client.files.create(
    file=(url, pseudo_file, "text/html"), purpose="assistants"
)
client.vector_stores.files.create(vector_store_id=vs.id, file_id=uploaded_file.id)
print(f"File uploaded and added to vector store: {uploaded_file.id}")

query = "How do you do great work?"
print(f"Query: {query}\n")

print(
    """
RAG using Responses API:
   - Automatic tool calling (model decides when to search)
   - Simpler code, less control
   - Best for: Conversational agents, automatic workflows

"""
)

print("Reply via Responses API:\n")
resp = client.responses.create(
    model=os.getenv("INFERENCE_MODEL", "ollama/llama3.2:3b"),
    input=query,
    tools=[{"type": "file_search", "vector_store_ids": [vs.id]}],
    include=["file_search_call.results"],
)

print("-" * 80)
print(resp.output[-1].content[-1].text)
print("-" * 80)

print(
    """

RAG using Chat Completions API:
   - Manual retrieval (you control the search)
   - More code, more control
   - Best for: Custom RAG patterns, batch processing, specialized workflows
"""
)

print("Searching vector store...")
search_results = client.vector_stores.search(
    vector_store_id=vs.id, query=query, max_num_results=3, rewrite_query=False
)

# Extract context from search results
context_chunks = []
for result in search_results.data:
    # result.content is a list of Content objects, extract the text from each
    for content_item in result.content:
        context_chunks.append(content_item.text)

context = "\n\n".join(context_chunks)
print(f"Found {len(context_chunks)} relevant chunks\n")

print("Reply via Chat Completions API:\n")
completion = client.chat.completions.create(
    model=os.getenv("INFERENCE_MODEL", "ollama/llama3.2:3b"),
    messages=[
        {
            "role": "system",
            "content": "You are a helpful assistant. Use the provided context to answer the user's question.",
        },
        {
            "role": "user",
            "content": f"Context:\n{context}\n\nQuestion: {query}\n\nPlease provide a comprehensive answer based on the context above.",
        },
    ],
    temperature=0.7,
)

print("-" * 80)
print(completion.choices[0].message.content)
print("-" * 80)

"""
gyliu-cary@Mac myls % uv run --with llama-stack-client,fire,requests demo_script.py
RAG demonstration

Fetching document from: https://www.paulgraham.com/greatwork.html
File uploaded and added to vector store: file-bee2cf9d96ab4100b5db4b62522ef627
Query: How do you do great work?


RAG using Responses API:
   - Automatic tool calling (model decides when to search)
   - Simpler code, less control
   - Best for: Conversational agents, automatic workflows


Reply via Responses API:

--------------------------------------------------------------------------------
To work on what you most want to work on, it's vital to find an approach that works for you and allows you to take calculated risks to achieve your goals, like when solving a mathematical equation. Great work usually entails spending time on a problem that genuinely interests you, even if it seems daunting, like Paul Graham suggests. Consistency is key – the more you focus consistently on something you’re genuinely interested in, the further you'll come,.

Consistency can lead to exponential growth and compound your efforts over time; it's essential to recognize exponential growth in progress and take steps accordingly, such as taking calculated risks and adapting strategies when necessary. To avoid setbacks from demoralizing you entirely, break them down and allow yourself to learn from failure or seek immediate improvement by seeking help, learning a new skill,<|file-DQrZ2M0LXh5OgJU1tBfS6Q==|>
--------------------------------------------------------------------------------


RAG using Chat Completions API:
   - Manual retrieval (you control the search)
   - More code, more control
   - Best for: Custom RAG patterns, batch processing, specialized workflows

Searching vector store...
Found 3 relevant chunks

Reply via Chat Completions API:

--------------------------------------------------------------------------------
The question of how to do great work is a complex one, and the author of this text suggests that there is no single definitive answer. However, based on the provided context, here are some key takeaways:

1. **Focus on developing your interests**: Rather than worrying about whether what you're working on is "important" or not, focus on doing something amazing that expands people's ideas of what's possible.
2. **Casting a wide net**: Curious people are more likely to find the right thing to work on because they cast a wide net and explore different possibilities.
3. **Being optimistic**: If you want to do great work, it's an advantage to be optimistic, even if that means taking risks and being vulnerable. Being cynical or pessimistic can hold you back from creating something truly remarkable.
4. **Finding your own voice**: Great work is consistent not only with who did it but also with itself. Be willing to take risks and try new things, rather than trying to conform to what others expect of you.
5. **Being a conduit for ideas**: When working on something that could be seen as either creation or discovery, err on the side of discovery. Try to see yourself as a mere conduit through which the ideas take their natural shape.
6. **Embracing effort and failure**: Doing great work is not easy, and you will need to put in effort and be willing to fail. Don't let modesty or fear hold you back from trying something new.
7. **Being honest with yourself**: Great work requires honesty with yourself, including being willing to cut things that don't fit or are holding you back.

Some additional tips that can be inferred from the text include:

* **Try to understand your own thought process and biases**: Recognize how your own thoughts and biases might influence your work.
* **Don't worry about being presumptuous**: If you have an idea, go for it. It's better to try something new than to play it safe and miss out on the opportunity to create something great.
* **Be patient and persistent**: Doing great work takes time, effort, and perseverance.

Overall, doing great work requires a combination of curiosity, optimism, creativity, and risk-taking, as well as a willingness to learn from your mistakes and be honest with yourself.
--------------------------------------------------------------------------------
"""
