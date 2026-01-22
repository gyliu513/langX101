from llama_stack_client import LlamaStackClient
from termcolor import colored


def _get_model_type(model) -> str | None:
    for attr in ("model_type", "type", "model_kind", "kind", "model_family"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
    return None


def _is_llm_model(model) -> bool:
    model_type = _get_model_type(model)
    # If the client schema doesn't expose type fields, assume LLM.
    return model_type is None or model_type == "llm"


def _get_model_id(model) -> str | None:
    for attr in ("identifier", "model_id", "id", "name"):
        value = getattr(model, attr, None)
        if isinstance(value, str):
            return value
    return None


def check_model_is_available(client: LlamaStackClient, model: str):
    available_models = [
        model_id
        for model in client.models.list()
        for model_id in [_get_model_id(model)]
        if model_id and _is_llm_model(model) and "guard" not in model_id
    ]

    if model not in available_models:
        print(
            colored(
                f"Model `{model}` not found. Available models:\n\n{available_models}\n",
                "red",
            )
        )
        return False

    return True


def get_any_available_model(client: LlamaStackClient):
    available_models = [
        model_id
        for model in client.models.list()
        for model_id in [_get_model_id(model)]
        if model_id and _is_llm_model(model) and "guard" not in model_id
    ]
    if not available_models:
        print(colored("No available models.", "red"))
        return None

    return available_models[0]
