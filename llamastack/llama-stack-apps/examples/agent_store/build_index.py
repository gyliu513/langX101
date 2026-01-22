import asyncio

import fire
from termcolor import cprint

from examples.agent_store.api import AgentStore


async def build_index(host, port, file_dir):
    api = AgentStore(host, port)
    vector_store_id = await api.build_index(file_dir)
    cprint(f"Successfully created vector store: {vector_store_id}", color="green")


def main(host: str, port: int, file_dir: str):
    asyncio.run(build_index(host, port, file_dir))


if __name__ == "__main__":
    fire.Fire(main)
