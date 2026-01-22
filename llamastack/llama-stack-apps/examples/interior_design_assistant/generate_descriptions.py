# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

# Copyright (c) Meta Platforms, Inc. and affiliates.
# This software may be used and distributed in accordance with the terms of the Llama 3 Community License Agreement.

import glob
import os
from pathlib import Path

import fire

from examples.interior_design_assistant.utils import (
    create_single_turn,
    data_url_from_image,
)

from llama_stack_client import LlamaStackClient
from examples.agents.utils import check_model_is_available


MODEL = "Llama3.2-11B-Vision-Instruct"


def _get_model_id(model) -> str | None:
    for attr in ("identifier", "model_id", "id", "name"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
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


def main(host: str, port: int, image_dir: str, output_dir: str):
    paths = []
    patterns = ["*.png", "*.jpeg", "*.jpg", "*.webp"]
    for p in patterns:
        for i, file_ in enumerate(glob.glob(os.path.join(image_dir, p))):
            paths.append(os.path.basename(file_))

    selected_model = MODEL
    # check if output dir exists, if not create it
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    memory_dir = Path(output_dir)

    client = LlamaStackClient(base_url=f"http://{host}:{port}")
    if not check_model_is_available(client, selected_model):
        fallback_model = _get_any_available_vision_model(client)
        if fallback_model is None:
            raise RuntimeError(
                "No vision-capable model found. Please start the stack with a vision model."
            )
        print(f"Model '{selected_model}' not found. Using '{fallback_model}' instead.")
        selected_model = fallback_model

    agent_kwargs = {
        "model": selected_model,
        "instructions": "",
    }

    paths = sorted(paths)
    for p in paths:
        full_path = os.path.join(image_dir, p)
        message = {
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": data_url_from_image(full_path),
                },
                {
                    "type": "input_text",
                    "text": "Describe the design, style, color, material and other aspects of the fireplace in this photo. Respond in one paragraph, no bullet points or sections.",
                },
            ],
        }

        response = create_single_turn(client, agent_kwargs, [message])
        response += "\n\n"
        response += f"<uri>{p}</uri>"

        with open(memory_dir / f"{p}.txt", "w") as f:
            f.write(response)

        print(f"Finished processing {p}")


if __name__ == "__main__":
    fire.Fire(main)
