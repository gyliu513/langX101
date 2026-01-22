# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import asyncio
import json
import re
import textwrap
from pathlib import Path
from typing import List

import fire

from examples.interior_design_assistant.utils import data_url_from_image
from examples.agents.utils import check_model_is_available, get_any_available_model

from llama_stack_client import LlamaStackClient

from termcolor import cprint

MODEL = "ollama/llama3.2-vision:latest"


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


def _get_any_available_vision_model(client: LlamaStackClient) -> str | None:
    candidates = []
    for model in client.models.list():
        model_id = _get_model_id(model)
        if not model_id:
            continue
        model_id_lower = model_id.lower()
        if any(token in model_id_lower for token in ("vision", "multimodal", "mm")):
            candidates.append(model_id)
    if candidates:
        return candidates[0]
    return None


class InterioAgent:
    def __init__(self, document_dir: str, image_dir: str):
        self.document_dir = document_dir
        self.image_dir = image_dir
        self.client = None
        self.vector_store_id = None
        self.vector_store_name = "interio_bank"
        self.vision_model_id = MODEL
        self.text_model_id = MODEL

    async def initialize(self, host: str, port: int):
        self.client = LlamaStackClient(base_url=f"http://{host}:{port}")
        if not check_model_is_available(self.client, self.vision_model_id):
            fallback_model = _get_any_available_vision_model(self.client)
            if fallback_model is None:
                raise RuntimeError(
                    "No vision-capable model found. Please start the stack with a vision model."
                )
            cprint(
                f"Model '{self.vision_model_id}' not found. Using '{fallback_model}' instead.",
                color="yellow",
            )
            self.vision_model_id = fallback_model
        self.text_model_id = get_any_available_model(self.client) or self.vision_model_id
        # setup memory bank for RAG
        self.vector_store_id = await self.build_vector_store(self.document_dir)

    def _run_response(
        self,
        messages,
        *,
        model_id: str,
        instructions: str | None = None,
        tools=None,
        include=None,
        text_format: dict | None = None,
    ):
        response = self.client.responses.create(
            model=model_id,
            input=messages,
            instructions=instructions,
            tools=tools,
            include=include,
            text={"format": text_format} if text_format else None,
            stream=False,
        )
        return response.output_text

    @staticmethod
    def _load_json(text: str):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Replace control characters that break JSON parsing.
        cleaned = re.sub(r"[\x00-\x1f]+", " ", text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Attempt to extract the first JSON object/array.
        for opener, closer in (("{", "}"), ("[", "]")):
            start = cleaned.find(opener)
            end = cleaned.rfind(closer)
            if start != -1 and end != -1 and end > start:
                snippet = cleaned[start : end + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    continue
        raise

    @staticmethod
    def _build_context_from_search(search_results) -> str:
        if not search_results:
            return ""
        context_lines = ["Context from retrieved documents:"]
        for result in search_results:
            snippet = " ".join(
                content.text.strip()
                for content in result.content
                if getattr(content, "text", None)
            ).strip()
            if not snippet:
                continue
            context_lines.append(f"- {result.filename} (score={result.score:.2f}): {snippet}")
        return "\n".join(context_lines)

    async def list_items(self, file_path: str) -> List[str]:
        """
        Analyze the image using multimodal llm
        and return a list of items that are present in the image.
        """
        assert self.client is not None, "Agent not initialized, call initialize() first"
        text = textwrap.dedent(
            """
            Analyze the image to provide a 4 sentence description of the architecture and furniture items present in it.
            Description should include architectural style, design, color, patterns, textures and other prominent details.
            Examples for furniture items include (but not limited to): couch, coffee table, fireplace, etc

            Return results in the following format:
            {
                "description": 4 sentence architectural description of the image,
                "items": list of furniture items present in the image
            }

            Remember to only list furniture items you see in the image. Just suggest item names without any additional text or explanations.
            For eg. "Couch" instead of "grey sectional couch"

            Please return as suggested format, Do not return any other text or explanations.
            """
        )
        image_data = data_url_from_image(file_path)

        message = {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": image_data},
                {"type": "input_text", "text": text},
            ],
        }

        result = self._run_response(
            [message],
            model_id=self.vision_model_id,
            text_format={
                "type": "json_schema",
                "name": "interior_list_items",
                "schema": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["description", "items"],
                },
            },
        )
        try:
            d = self._load_json(result.strip())
        except Exception:
            cprint(f"Error parsing JSON output: {result}", color="red")
            raise

        return d

    async def suggest_alternatives(
        self, file_path: str, item: str, n: int = 3
    ) -> List[str]:
        """
        Analyze the image using multimodal llm
        and return possible alternative descriptions for the provided item.
        """
        prompt = textwrap.dedent(
            """
            For the given image, your task is to carefully examine the image to provide alternative suggestions for {item}.
            The {item} should fit well with the overall aesthetic of the room.

            Carefully analyze the image, paying attention to the overall style, design, color, patterns, materials and architectural details.
            Based on your analysis, generate a 1-2 sentence detailed alternative descritions for the {item} that would complement the room's aesthetic.
            The descriptions should be detailed mentioning the style, color, material, and any other relevant details that would help in a search query
            Each alternative should be different from each other but still fit harmoniously within the space.

            Each description should be 10-20 words long and should be on a separate line.
            Return results in the following format:
            [
                {{
                    "description": first alternative suggestion of the item
                }},
                {{
                    "description": second alternative suggestion of the item
                }},
            ]

            Only provide {n} alternative descriptions, nothing else.
            Return JSON as suggested, Do not return any other text or explanations. Don't forget the ',' at the end of each description.
            """
        )

        text = prompt.format(item=item, n=n)
        image_data = data_url_from_image(file_path)

        message = {
            "role": "user",
            "content": [
                {"type": "input_image", "image_url": image_data},
                {
                    "type": "input_text",
                    "text": text,
                },
            ],
        }

        result = self._run_response(
            [message],
            model_id=self.vision_model_id,
            text_format={
                "type": "json_schema",
                "name": "interior_suggest_alternatives",
                "schema": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]},
                },
            },
        )
        print(result)
        return [r["description"].strip() for r in self._load_json(result.strip())]

    async def retrieve_images(self, description: str):
        """
        Retrieve images from the memory bank that match the description
        """
        assert self.vector_store_id is not None, "Setup store via initialize()"

        prompt = textwrap.dedent(
            """
            You are given a description of an item.
            Your task is to find images of that item in the documents that match the description.
            Return the top 4 most relevant results.

            Return results in the following format:
            [
                {
                    "image": "uri value",
                    "description": "description of the image",
                },
                {
                    "image": "uri value",
                    "description": "description of the image 2",
                }
            ]
            The uri value is enclosed in the tags <uri> and </uri>.
            The description is a summarized explanation of why this item is relevant and how it can enhance the room.

            Return JSON as suggested, Do not return any other text or explanations.
            Do not create uri values, return actual uri value (eg. "011.webp") as is.
            """
        )
        description = f"Description: {description}"
        message = {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_text", "text": description},
            ],
        }

        search_response = self.client.vector_stores.search(
            vector_store_id=self.vector_store_id,
            query=description,
            max_num_results=5,
        )
        context = self._build_context_from_search(search_response.data)
        instructions = "You are a helpful assistant."
        if context:
            instructions = f"{instructions}\n\n{context}"
        response = self._run_response(
            [message],
            model_id=self.text_model_id,
            instructions=instructions,
            text_format={
                "type": "json_schema",
                "name": "interior_retrieve_images",
                "schema": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "image": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["image", "description"],
                    },
                },
            },
        )
        return self._load_json(response.strip())

    # NOTE: If using a persistent memory bank, building on the fly is not needed
    # and LlamaStack apis can leverage existing banks
    async def build_vector_store(self, local_dir: str) -> str:
        """
        Build a vector store that can be used to store and retrieve images.
        """
        local_dir = Path(local_dir)
        vector_store = next(
            (
                store
                for store in self.client.vector_stores.list()
                if store.name == self.vector_store_name
            ),
            None,
        )
        if vector_store is None:
            embedding_model = _get_any_available_embedding_model(self.client)
            if embedding_model is None:
                raise RuntimeError("No available embedding model found.")
            embedding_dimension = _get_embedding_dimension(self.client, embedding_model)
            if embedding_dimension is None:
                raise RuntimeError("Unable to determine embedding dimension.")
            vector_providers = [
                provider
                for provider in self.client.providers.list()
                if provider.api == "vector_io"
            ]
            if not vector_providers:
                raise RuntimeError("No available vector_io providers.")
            vector_store = self.client.vector_stores.create(
                name=self.vector_store_name,
                extra_body={
                    "provider_id": vector_providers[0].provider_id,
                    "embedding_model": embedding_model,
                    "embedding_dimension": embedding_dimension,
                },
            )

        if vector_store.file_counts.total == 0:
            for file in local_dir.iterdir():
                if not file.is_file():
                    continue
                with file.open("rb") as handle:
                    uploaded = self.client.files.create(
                        file=handle,
                        purpose="assistants",
                    )
                self.client.vector_stores.files.create(
                    vector_store_id=vector_store.id,
                    file_id=uploaded.id,
                    attributes={"document_id": file.name},
                    chunking_strategy={
                        "type": "static",
                        "static": {
                            "max_chunk_size_tokens": 512,
                            "chunk_overlap_tokens": 0,
                        },
                    },
                )

        return vector_store.id


async def async_main(host: str, port: int, memory_path: str, image_dir: str):
    interio = InterioAgent(memory_path, image_dir)
    await interio.initialize(host, port)

    # Test query to ensure memory bank is working
    # query = (
    #     "A rustic, stone-faced fireplace with a wooden mantel and a cast-iron insert."
    # )
    # res = interio.client.tool_runtime.rag_tool.query(
    #     vector_db_id=interio.bank_id,
    #     query=query,
    # )
    # print(res)

    path = input(
        "Enter Image path (relative to image_dir or memory_path is accepted) >> "
    )

    path = Path(path)

    options = [
        path,
        Path(image_dir) / path,
        Path(memory_path) / path,
    ]
    chosen_path = None
    for p in options:
        if p.exists():
            chosen_path = p
            break

    if not chosen_path:
        cprint(f"No valid path found in {options}", color="red")
        return

    if chosen_path.is_dir():
        image_exts = {".png", ".jpg", ".jpeg", ".webp"}
        image_files = sorted(
            [p for p in chosen_path.iterdir() if p.is_file() and p.suffix.lower() in image_exts]
        )
        if not image_files:
            cprint(f"No image files found in directory: {chosen_path}", color="red")
            return
        chosen_path = image_files[0]
        cprint(f"Using first image in directory: {chosen_path.name}", color="yellow")

    result = await interio.list_items(chosen_path)

    cprint(f"Here is the description: {result['description']}", color="yellow")
    cprint(f"Here are the identified items: {result['items']}", color="yellow")
    item = input("Which item do you want to change? >> ")
    alternatives = await interio.suggest_alternatives(chosen_path, item)
    alt_str = "\n- ".join(alternatives)
    cprint(f"Here are the suggested alternatives: \n- {alt_str}", color="yellow")

    choice = input("Which alternative did you like? >> ")
    res = await interio.retrieve_images(alternatives[int(choice)])

    print("Here are some ideas")
    for r in res:
        cprint(f"{r['image']}", color="green")
        cprint(f"{r['description']}", color="yellow")


def main(host: str, port: int, memory_path: str, image_dir: str):
    asyncio.run(async_main(host, port, memory_path, image_dir))


if __name__ == "__main__":
    fire.Fire(main)
