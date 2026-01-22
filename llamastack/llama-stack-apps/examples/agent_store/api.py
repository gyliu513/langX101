# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import os
import sys
import textwrap
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from llama_stack_client import Agent, LlamaStackClient

from termcolor import colored

from examples.agents.utils import get_any_available_model
from .utils import data_url_from_file

load_dotenv()


class AgentChoice(Enum):
    WebSearch = "WebSearch"
    Memory = "Memory"


class AgentStore:
    def __init__(self, host, port) -> None:
        self.client = LlamaStackClient(base_url=f"http://{host}:{port}")
        self.model = get_any_available_model(self.client)
        if not self.model:
            print(colored("No available models. Exiting.", "red"))
            sys.exit(1)
        print(f"Using model: {self.model}")

        self.agents = {}
        self.sessions = {}
        self.vector_store_ids = []
        self.live_bank_id = None

    async def initialize_agents(self, vector_db_ids: List[str]) -> None:
        self.agents[AgentChoice.WebSearch] = await self.get_agent(
            agent_type=AgentChoice.WebSearch
        )
        self.create_session(AgentChoice.WebSearch)
        # Create a live bank that holds live context
        self.live_bank_id = self.create_live_bank()

        self.vector_store_ids = vector_db_ids
        self.agents[AgentChoice.Memory] = await self.get_agent(
            agent_type=AgentChoice.Memory,
            agent_params={
                "vector_store_ids": self.vector_store_ids + [self.live_bank_id]
            },
        )
        self.create_session(AgentChoice.Memory)

    def create_live_bank(self):
        response = self.client.vector_stores.create(name="live_bank")
        # FIXME: To avoid empty banks
        self.append_to_live_memory_bank(
            "This is a live bank. It holds live context for this chat"
        )
        return response.id

    async def get_agent(
        self,
        agent_type: AgentChoice,
        agent_params: Optional[Dict[str, Any]] = None,
    ) -> Agent:
        agent_params = agent_params or {}
        if agent_type == AgentChoice.WebSearch:
            if "BRAVE_SEARCH_API_KEY" not in os.environ:
                print(
                    colored(
                        "You must set the BRAVE_SEARCH_API_KEY environment variable to use this example.",
                        "red",
                    )
                )
                sys.exit(1)

            toolgroups = [
                {
                    "type": "web_search",
                    "search_context_size": "medium",
                }
            ]
            user_instructions = textwrap.dedent(
                """
                You are an agent that can search the web (using brave_search) to answer user questions.

                Your task is to search the web to get the information related to the provided question.
                Ask clarifying questions if needed to figure out appropriate search query.
                Cite the top sources with corresponding urls.
                Once you make a relevant search query, summarize the results to answer in the following format:
                ```
                This is what I found on the web:
                {add answer here}

                Sources:
                {add sources with corresponding links}
                ```
                Do NOT add any other greetings or explanations. Just make a search call and answer in the appropriate format.
                """
            )
        elif agent_type == AgentChoice.Memory:
            vector_store_ids = agent_params.get("vector_store_ids", [])
            toolgroups = [
                {
                    "type": "file_search",
                    "vector_store_ids": vector_store_ids,
                    "max_num_results": 5,
                }
            ]
            user_instructions = ""
        else:
            toolgroups = []
            user_instructions = ""

        return Agent(
            self.client,
            model=self.model,
            instructions=user_instructions,
            tools=toolgroups,
        )

    def create_session(self, agent_choice: str) -> str:
        agent = self.agents[agent_choice]
        session_id = agent.create_session(f"Session-{uuid.uuid4()}")
        self.sessions[agent_choice] = session_id
        return self.sessions[agent_choice]

    async def build_index(self, file_dir: str) -> str:
        """Build a vector index from a directory of pdf files."""

        # 1. create vector store
        vector_store = self.client.vector_stores.create(name="vector_store")

        # 2. load pdfs from directory as raw text
        paths = []
        for filename in os.listdir(file_dir):
            if filename.endswith(".pdf"):
                file_path = os.path.join(file_dir, filename)
                paths.append(file_path)

        chunks = [
            {
                "chunk_id": uuid.uuid4().hex,
                "content": data_url_from_file(path),
                "metadata": {"document_id": os.path.basename(path)},
            }
            for path in paths
        ]
        if chunks:
            self.client.vector_io.insert(
                vector_store_id=vector_store.id,
                chunks=chunks,
            )

        return vector_store.id

    async def chat(self, agent_choice, message, attachments) -> str:
        assert (
            agent_choice in self.agents
        ), f"Agent of type {agent_choice} not initialized"
        agent = self.agents[agent_choice]
        session_id = self.sessions[agent_choice]
        content = [{"type": "input_text", "text": message}]
        if attachments is not None:
            for attachment in attachments:
                content.append(
                    {
                        "type": "input_file",
                        "file_data": data_url_from_file(attachment),
                        "filename": os.path.basename(attachment),
                    }
                )
        response = agent.create_turn(
            messages=[{"role": "user", "content": content}],
            session_id=session_id,
            stream=False,
        )

        inserted_context = ""
        output_items = getattr(response, "output", []) or []
        for output_item in output_items:
            output_type = getattr(output_item, "type", None)
            if output_type != "file_search_call":
                continue
            results = getattr(output_item, "results", None) or []
            result_texts = []
            for result in results:
                text = getattr(result, "text", None)
                if isinstance(text, str) and text:
                    result_texts.append(text)
            if result_texts:
                inserted_context = "\n".join(result_texts)

        output_text = getattr(response, "output_text", None)
        if output_text is None:
            output_message = getattr(response, "output_message", None)
            output_text = getattr(output_message, "content", "")
        return output_text, inserted_context

    def append_to_live_memory_bank(self, text: str) -> None:
        if not self.live_bank_id:
            return
        self.client.vector_io.insert(
            vector_store_id=self.live_bank_id,
            chunks=[
                {
                    "chunk_id": uuid.uuid4().hex,
                    "content": text,
                    "metadata": {"source": "live_bank"},
                }
            ],
        )

    async def clear_live_bank(self) -> None:
        # FIXME: This is a hack, ideally we should
        # clear an existing bank instead of creating a new one
        self.live_bank_id = self.create_live_bank()
        self.agents[AgentChoice.Memory] = await self.get_agent(
            agent_type=AgentChoice.Memory,
            agent_params={
                "vector_store_ids": self.vector_store_ids + [self.live_bank_id]
            },
        )
        self.create_session(AgentChoice.Memory)
