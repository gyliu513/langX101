# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from io import BytesIO
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4

import fire
import time
from llama_stack_client import Agent, AgentEventLogger, LlamaStackClient
from termcolor import colored

from .utils import check_model_is_available, get_any_available_model


def _get_model_type(model) -> str | None:
    for attr in ("model_type", "type", "model_kind", "kind", "model_family"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
    for metadata_attr in ("custom_metadata", "metadata"):
        metadata = getattr(model, metadata_attr, None)
        if isinstance(metadata, dict):
            value = metadata.get("model_type") or metadata.get("type")
            if isinstance(value, str):
                return value
    return None


def _get_model_id(model) -> str | None:
    for attr in ("identifier", "model_id", "id", "name"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
    return None


def _get_any_available_embedding_model(client: LlamaStackClient) -> str | None:
    embedding_models = [
        model_id
        for model in client.models.list()
        for model_id in [_get_model_id(model)]
        if model_id
        and (
            _get_model_type(model) == "embedding"
            or "embedding" in model_id.lower()
            or "embed" in model_id.lower()
        )
    ]
    if not embedding_models:
        print(colored("No available embedding models.", "red"))
        return None
    return embedding_models[0]


def _get_embedding_dimension(client: LlamaStackClient, model_id: str) -> int | None:
    try:
        response = client.embeddings.create(model=model_id, input="dimension probe")
    except Exception:
        return None
    if not response.data:
        return None
    embedding = response.data[0].embedding
    if isinstance(embedding, list):
        return len(embedding)
    return None


def main(
    host: str,
    port: int,
    model_id: str | None = None,
    embedding_model_id: str | None = None,
):
    urls = [
        "memory_optimizations.rst",
        "chat.rst",
        "llama3.rst",
        "qat_finetune.rst",
        "lora_finetune.rst",
    ]
    document_urls = [
        f"https://raw.githubusercontent.com/pytorch/torchtune/main/docs/source/tutorials/{url}"
        for url in urls
    ]

    client = LlamaStackClient(base_url=f"http://{host}:{port}")

    if model_id is None:
        model_id = get_any_available_model(client)
        if model_id is None:
            return
    else:
        if not check_model_is_available(client, model_id):
            return

    print(f"Using model: {model_id}")

    embedding_model = embedding_model_id or _get_any_available_embedding_model(client)
    if embedding_model is None:
        return

    embedding_dimension = _get_embedding_dimension(client, embedding_model)
    if embedding_dimension is None:
        print(colored("Unable to determine embedding dimension.", "red"))
        return

    vector_providers = [
        provider for provider in client.providers.list() if provider.api == "vector_io"
    ]
    if not vector_providers:
        print(colored("No available vector_io providers. Exiting.", "red"))
        return

    selected_vector_provider = vector_providers[0]

    # Create a vector store
    vector_store = client.vector_stores.create(
        name=f"test_vector_store_{uuid4()}",
        extra_body={
            "provider_id": selected_vector_provider.provider_id,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
        },
    )

    # Upload and attach documents to the vector store
    start_time = time.time()
    for i, url in enumerate(document_urls):
        with urlopen(url) as response:
            file_buffer = BytesIO(response.read())
        filename = urlparse(url).path.rsplit("/", 1)[-1] or f"document-{i}.txt"
        file_buffer.name = filename
        uploaded_file = client.files.create(file=file_buffer, purpose="assistants")
        client.vector_stores.files.create(
            vector_store_id=vector_store.id,
            file_id=uploaded_file.id,
            attributes={"document_id": f"num-{i}", "source": url},
            chunking_strategy={
                "type": "static",
                "static": {"max_chunk_size_tokens": 512, "chunk_overlap_tokens": 128},
            },
        )
    end_time = time.time()
    print(colored(f"Inserted documents in {end_time - start_time:.2f}s", "cyan"))

    agent = Agent(
        client,
        model=model_id,
        instructions="You are a helpful assistant. Use file_search tool to gather information needed to answer questions. Answer succintly.",
        tools=[
            {
                "type": "file_search",
                "vector_store_ids": [vector_store.id],
            }
        ],
    )
    session_id = agent.create_session("test-session")
    print(f"Created session_id={session_id}")

    user_prompts = [
        "Is anything related to 'Llama3' mentioned, if so what?",
        "Tell me how to use LoRA",
        "What about Quantization?",
    ]

    for prompt in user_prompts:
        response = agent.create_turn(
            messages=[{"role": "user", "content": prompt}],
            session_id=session_id,
        )
        print(colored(f"User> {prompt}", "blue"))
        for printable in AgentEventLogger().log(response):
            print(printable, end="", flush=True)


if __name__ == "__main__":
    fire.Fire(main)
