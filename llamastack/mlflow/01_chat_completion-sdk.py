"""
Demo: OpenAI-Compatible Chat Completion

Description:
This demo shows that existing OpenAI chat-completion code works against a
Llama Stack server with only a base_url change.

Learning Objectives:
- Use the OpenAI Python SDK to talk to Llama Stack
- Perform non-streaming and streaming chat completions
- Resolve an available model via the OpenAI-compatible models endpoint
"""

"""
sqlite3 /tmp/llama-telemetry/mlflow/mlflow.db "SELECT count(*) FROM trace_info;"
sqlite> .schema trace_info
CREATE TABLE trace_info (
	request_id VARCHAR(50) NOT NULL,
	experiment_id INTEGER NOT NULL,
	timestamp_ms BIGINT NOT NULL,
	execution_time_ms BIGINT,
	status VARCHAR(50) NOT NULL, client_request_id VARCHAR(50), request_preview VARCHAR(1000), response_preview VARCHAR(1000),
	CONSTRAINT trace_info_pk PRIMARY KEY (request_id),
	CONSTRAINT fk_trace_info_experiment_id FOREIGN KEY(experiment_id) REFERENCES experiments (experiment_id)
);
CREATE INDEX index_trace_info_experiment_id_timestamp_ms ON trace_info (experiment_id, timestamp_ms);
sqlite>
sqlite> select count(*) FROM trace_info where experiment_id=1;
2
sqlite> select count(*) FROM trace_info where experiment_id=0;
87
cd /Users/gualiu/llamastack/llama-stack-demos && MLFLOW_ENABLE_TRACING=1 MLFLOW_TRACKING_URI=http://localhost:5000 uv run python -m demos.06_openai_compatibility.01_chat_completion-sdk localhost 8321 --stream
"""

# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

from __future__ import annotations
import mlflow

import os
import sys

import fire
from openai import OpenAI

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.utils import resolve_openai_model

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    load_dotenv = None


def _maybe_load_dotenv() -> None:
    if load_dotenv is not None:
        load_dotenv()


def _print_stream(stream) -> None:
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
    print()


def main(
    host: str,
    port: int,
    model_id: str | None = None,
    prompt: str = "Give me a short summary of Llama Stack.",
    stream: bool = False,
    scheme: str = "http",
) -> None:
    _maybe_load_dotenv()

    if scheme not in {"http", "https"}:
        raise ValueError("scheme must be 'http' or 'https'")
    if host not in {"localhost", "127.0.0.1", "::1"} and scheme != "https":
        print("Warning: using HTTP for a non-local host. Consider --scheme https.")

    print(f"MLflow version: {mlflow.__version__}")
    print(f"OpenAI python version: {OpenAI.__module__.split('.')[0]} pkg version unknown")
    import openai
    print(f"openai pkg version: {openai.__version__}")
    print(f"Tracking URI in use: {mlflow.get_tracking_uri()}")

    # Explicitly enable tracing and OpenAI autologging.
    import mlflow.tracing as mlflow_tracing
    mlflow_tracing.enable()
    mlflow.openai.autolog()


    client = OpenAI(
        base_url=f"{scheme}://{host}:{port}/v1",
        api_key=os.getenv("LLAMA_STACK_API_KEY", "fake"),
    )

    resolved_model = resolve_openai_model(client, model_id)
    if resolved_model is None:
        return
    print(f"Using model: {resolved_model}")

    messages = [{"role": "user", "content": prompt}]

    if stream:
        response_stream = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
            stream=True,
        )
        _print_stream(response_stream)
        response_stream.close()
        return

    from mlflow.tracing import fluent as tracing_fluent

    with tracing_fluent.start_span("chat_completion", span_type="CHAT_MODEL") as span:
        span.set_inputs({"model": resolved_model, "messages": messages})
        completion = client.chat.completions.create(
            model=resolved_model,
            messages=messages,
        )
        span.set_outputs(completion.model_dump())

    print(completion.choices[0].message.content)


if __name__ == "__main__":
    fire.Fire(main)
