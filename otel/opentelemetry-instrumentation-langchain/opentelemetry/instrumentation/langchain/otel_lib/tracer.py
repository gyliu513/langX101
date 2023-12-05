import json
import logging
from copy import deepcopy
# from datetime import datetime
import datetime
from datetime import timezone
import time
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple
from uuid import UUID

from langchain.callbacks.tracers.base import BaseTracer
from langchain.callbacks.tracers.schemas import Run
from langchain.load.dump import dumpd
from langchain.schema.messages import BaseMessage

from opentelemetry.semconv.ai import SpanAttributes, TraceloopSpanKindValues
from opentelemetry import trace
from opentelemetry.trace import get_tracer
from opentelemetry.instrumentation.langchain.version import __version__


from phoenix.trace.exporter import HttpExporter
from phoenix.trace.schemas import Span, SpanEvent, SpanException, SpanKind, SpanStatusCode
from phoenix.trace.semantic_conventions import (
    DOCUMENT_CONTENT,
    DOCUMENT_METADATA,
    INPUT_MIME_TYPE,
    INPUT_VALUE,
    LLM_FUNCTION_CALL,
    LLM_INPUT_MESSAGES,
    LLM_INVOCATION_PARAMETERS,
    LLM_MODEL_NAME,
    LLM_OUTPUT_MESSAGES,
    LLM_PROMPT_TEMPLATE,
    LLM_PROMPT_TEMPLATE_VARIABLES,
    LLM_PROMPT_TEMPLATE_VERSION,
    LLM_PROMPTS,
    LLM_TOKEN_COUNT_COMPLETION,
    LLM_TOKEN_COUNT_PROMPT,
    LLM_TOKEN_COUNT_TOTAL,
    MESSAGE_CONTENT,
    MESSAGE_FUNCTION_CALL_ARGUMENTS_JSON,
    MESSAGE_FUNCTION_CALL_NAME,
    MESSAGE_ROLE,
    OUTPUT_MIME_TYPE,
    OUTPUT_VALUE,
    RETRIEVAL_DOCUMENTS,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    MimeType,
)
from phoenix.trace.tracer import Tracer
from phoenix.utilities.error_handling import graceful_fallback

logger = logging.getLogger(__name__)


Message = Dict[str, Any]


def _langchain_run_type_to_span_kind(run_type: str) -> SpanKind:
    # TODO: LangChain is moving away from enums and to arbitrary strings
    # for the run_type variable, so we may need to do the same
    try:
        return SpanKind(run_type.upper())
    except ValueError:
        return SpanKind.UNKNOWN


def _serialize_json(obj: Any) -> str:
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    return str(obj)


def _convert_io(obj: Optional[Dict[str, Any]]) -> Iterator[Any]:
    if not obj:
        return
    if not isinstance(obj, dict):
        raise ValueError(f"obj should be dict, but obj={obj}")
    if len(obj) == 1 and isinstance(value := next(iter(obj.values())), str):
        yield value
    else:
        yield json.dumps(obj, default=_serialize_json)
        yield MimeType.JSON


def _prompts(run_inputs: Dict[str, Any]) -> Iterator[Tuple[str, List[str]]]:
    """Yields prompts if present."""
    if "prompts" in run_inputs:
        yield LLM_PROMPTS, run_inputs["prompts"]


def _input_messages(run_inputs: Mapping[str, Any]) -> Iterator[Tuple[str, List[Message]]]:
    """Yields chat messages if present."""
    if not hasattr(run_inputs, "get"):
        return
    # There may be more than one set of messages. We'll use just the first set.
    if not (multiple_messages := run_inputs.get("messages")):
        return
    assert isinstance(
        multiple_messages, Iterable
    ), f"expected Iterable, found {type(multiple_messages)}"
    # This will only get the first set of messages.
    if not (first_messages := next(iter(multiple_messages), None)):
        return
    assert isinstance(first_messages, Iterable), f"expected Iterable, found {type(first_messages)}"
    parsed_messages = []
    for message_data in first_messages:
        assert hasattr(message_data, "get"), f"expected Mapping, found {type(message_data)}"
        parsed_messages.append(_parse_message_data(message_data))
    if parsed_messages:
        yield LLM_INPUT_MESSAGES, parsed_messages


def _output_messages(run_outputs: Mapping[str, Any]) -> Iterator[Tuple[str, List[Message]]]:
    """Yields chat messages if present."""
    if not hasattr(run_outputs, "get"):
        return
    # There may be more than one set of generations. We'll use just the first set.
    if not (multiple_generations := run_outputs.get("generations")):
        return
    assert isinstance(
        multiple_generations, Iterable
    ), f"expected Iterable, found {type(multiple_generations)}"
    # This will only get the first set of generations.
    if not (first_generations := next(iter(multiple_generations), None)):
        return
    assert isinstance(
        first_generations, Iterable
    ), f"expected Iterable, found {type(first_generations)}"
    parsed_messages = []
    for generation in first_generations:
        assert hasattr(generation, "get"), f"expected Mapping, found {type(generation)}"
        if message_data := generation.get("message"):
            assert hasattr(message_data, "get"), f"expected Mapping, found {type(message_data)}"
            parsed_messages.append(_parse_message_data(message_data))
    if parsed_messages:
        yield LLM_OUTPUT_MESSAGES, parsed_messages


def _parse_message_data(message_data: Mapping[str, Any]) -> Message:
    """Parses message data to grab message role, content, etc."""
    message_class_name = message_data["id"][-1]
    if message_class_name.startswith("HumanMessage"):
        role = "user"
    elif message_class_name.startswith("AIMessage"):
        role = "assistant"
    elif message_class_name.startswith("SystemMessage"):
        role = "system"
    elif message_class_name.startswith("FunctionMessage"):
        role = "function"
    elif message_class_name.startswith("ChatMessage"):
        role = message_data["kwargs"]["role"]
    else:
        raise ValueError(f"Cannot parse message of type: {message_class_name}")
    parsed_message_data = {MESSAGE_ROLE: role}
    if kwargs := message_data.get("kwargs"):
        assert hasattr(kwargs, "get"), f"expected Mapping, found {type(kwargs)}"
        if content := kwargs.get("content"):
            assert isinstance(content, str), f"content must be str, found {type(content)}"
            parsed_message_data[MESSAGE_CONTENT] = content
        if additional_kwargs := kwargs.get("additional_kwargs"):
            assert hasattr(
                additional_kwargs, "get"
            ), f"expected Mapping, found {type(additional_kwargs)}"
            if function_call := additional_kwargs.get("function_call"):
                assert hasattr(
                    function_call, "get"
                ), f"expected Mapping, found {type(function_call)}"
                if name := function_call.get("name"):
                    assert isinstance(name, str), f"name must be str, found {type(name)}"
                    parsed_message_data[MESSAGE_FUNCTION_CALL_NAME] = name
                if arguments := function_call.get("arguments"):
                    assert isinstance(
                        arguments, str
                    ), f"arguments must be str, found {type(arguments)}"
                    parsed_message_data[MESSAGE_FUNCTION_CALL_ARGUMENTS_JSON] = arguments
    return parsed_message_data


def _prompt_template(run_serialized: Dict[str, Any]) -> Iterator[Tuple[str, Any]]:
    """
    A best-effort attempt to locate the PromptTemplate object among the
    keyword arguments of a serialized object, e.g. an LLMChain object.
    """
    for obj in run_serialized.get("kwargs", {}).values():
        if not isinstance(obj, dict) or "id" not in obj:
            continue
        # The `id` field of the object is a list indicating the path to the
        # object's class in the LangChain package, e.g. `PromptTemplate` in
        # the `langchain.prompts.prompt` module is represented as
        # ["langchain", "prompts", "prompt", "PromptTemplate"]
        if obj["id"][-1].endswith("PromptTemplate"):
            kwargs = obj.get("kwargs", {})
            if not (template := kwargs.get("template", "")):
                continue
            yield LLM_PROMPT_TEMPLATE, template
            yield LLM_PROMPT_TEMPLATE_VARIABLES, kwargs.get("input_variables", [])
            yield LLM_PROMPT_TEMPLATE_VERSION, "unknown"
            break


def _invocation_parameters(run: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """Yields invocation parameters if present."""
    if run["run_type"] != "llm":
        return
    run_extra = run["extra"]
    yield LLM_INVOCATION_PARAMETERS, json.dumps(run_extra.get("invocation_params", {}))


def _model_name(run_extra: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """Yields model name if present."""
    if not (invocation_params := run_extra.get("invocation_params")):
        return
    for key in ["model_name", "model"]:
        if name := invocation_params.get(key):
            yield LLM_MODEL_NAME, name
            return


def _token_counts(run_outputs: Dict[str, Any]) -> Iterator[Tuple[str, int]]:
    """Yields token count information if present."""
    try:
        token_usage = run_outputs["llm_output"]["token_usage"]
    except Exception:
        return
    for attribute_name, key in [
        (LLM_TOKEN_COUNT_PROMPT, "prompt_tokens"),
        (LLM_TOKEN_COUNT_COMPLETION, "completion_tokens"),
        (LLM_TOKEN_COUNT_TOTAL, "total_tokens"),
    ]:
        if (token_count := token_usage.get(key)) is not None:
            yield attribute_name, token_count


def _function_calls(run_outputs: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """Yields function call information if present."""
    try:
        function_call_data = deepcopy(
            run_outputs["generations"][0][0]["message"]["kwargs"]["additional_kwargs"][
                "function_call"
            ]
        )
        function_call_data["arguments"] = json.loads(function_call_data["arguments"])
        yield LLM_FUNCTION_CALL, json.dumps(function_call_data)
    except Exception:
        pass


def _tools(run: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """Yields tool attributes if present."""
    if run["run_type"] != "tool":
        return
    run_serialized = run["serialized"]
    if "name" in run_serialized:
        yield TOOL_NAME, run_serialized["name"]
    if "description" in run_serialized:
        yield TOOL_DESCRIPTION, run_serialized["description"]
    # TODO: tool parameters https://github.com/Arize-ai/phoenix/issues/1330


def _retrieval_documents(
    run: Dict[str, Any],
) -> Iterator[Tuple[str, List[Any]]]:
    if run["run_type"] != "retriever":
        return
    yield (
        RETRIEVAL_DOCUMENTS,
        [
            {
                DOCUMENT_CONTENT: document.get("page_content"),
                DOCUMENT_METADATA: document.get("metadata") or {},
            }
            for document in (run.get("outputs") or {}).get("documents") or []
        ],
    )


def _chat_model_start_fallback(
    serialized: Dict[str, Any],
    messages: List[List[BaseMessage]],
    *,
    run_id: UUID,
    tags: Optional[List[str]] = None,
    parent_run_id: Optional[UUID] = None,
    metadata: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    # Currently does nothing. If a functional fallback is implemented, new failures will not be
    # caught
    pass


def _set_span_attribute(span, name, value):
    if value is not None:
        if value != "":
            span.set_attribute(name, value)
    return

def _extract_llm_parms(instance, span):
    if hasattr(instance, "llm"):
        _set_span_attribute(span, SpanAttributes.LLM_TEMPERATURE, instance.llm.temperature)
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, instance.llm.model_name)
        if hasattr(instance, "prompt"):
            for msg in instance.prompt.messages:
                if msg.__class__.__name__ == "SystemMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.system", msg.content)
                elif msg.__class__.__name__ == "HumanMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.user", msg.content)
                elif msg.__class__.__name__ == "HumanMessagePromptTemplate":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.user", msg.prompt.template)
    return

def _get_timestamp(time_data): 
    utc_time=time_data.replace(tzinfo=timezone.utc) 
    return int(utc_time.timestamp()*10**9)
            
class OpenInferenceTracer(BaseTracer):  # type: ignore 
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.tracer = None

    def _convert_run_to_spans(
        self,
        run: Dict[str, Any],
        parent: Optional[Span] = None,
    ) -> None:

        span_kind = (
            SpanKind.AGENT
            if "agent" in run["name"].lower()
            else _langchain_run_type_to_span_kind(run["run_type"])
        )
        span_name = run["name"] if run["name"] is not None and run["name"] != "" else str(span_kind)

        # span = self.tracer.start_span(span_name, start_time=start_time)
        # with trace.use_span(span, end_on_exit=False):
        start_time=_get_timestamp(run["start_time"])
        with self.tracer.start_as_current_span(span_name, start_time=start_time, end_on_exit=False) as span:        
            span.set_attribute(
                SpanAttributes.TRACELOOP_SPAN_KIND,
                str(span_kind),
            )
            span.set_attribute(SpanAttributes.TRACELOOP_ENTITY_NAME, span_name)
        
            for child_run in run["child_runs"]:
                self._convert_run_to_spans(child_run)

        end_time=_get_timestamp(run["end_time"])
        span.end(end_time=end_time)

    def _persist_run(self, run: Run) -> None:
        # Note that this relies on `.dict()` from pydantic for the
        # serialization of objects like `langchain.schema.Document`.
        try:
            self._convert_run_to_spans(run.dict())
        except Exception:
            logger.exception("Failed to convert run to spans")

    @graceful_fallback(_chat_model_start_fallback)
    def on_chat_model_start(
        self,
        serialized: Dict[str, Any],
        messages: List[List[BaseMessage]],
        *,
        run_id: UUID,
        tags: Optional[List[str]] = None,
        parent_run_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """
        Adds chat messages to the run inputs.

        LangChain's BaseTracer class does not implement hooks for chat models and hence does not
        record data such as the list of messages that were passed to the chat model.

        For reference, see https://github.com/langchain-ai/langchain/pull/4499.
        """

        parent_run_id_ = str(parent_run_id) if parent_run_id else None
        execution_order = self._get_execution_order(parent_run_id_)
        start_time = datetime.datetime.utcnow()
        if metadata:
            kwargs.update({"metadata": metadata})
        run = Run(
            id=run_id,
            parent_run_id=parent_run_id,
            serialized=serialized,
            inputs={"messages": [[dumpd(message) for message in batch] for batch in messages]},
            extra=kwargs,
            events=[{"name": "start", "time": start_time}],
            start_time=start_time,
            execution_order=execution_order,
            child_execution_order=execution_order,
            run_type="llm",
            tags=tags,
            name=name or "",
        )
        self._start_trace(run)
