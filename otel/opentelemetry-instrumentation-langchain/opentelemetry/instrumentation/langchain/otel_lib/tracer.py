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

# need to use `opentelemetry.semconv.ai` under `opentelemetry-semantic-conventions-ai`
# from opentelemetry.semconv.ai import SpanAttributes, TraceloopSpanKindValues
from ai import SpanAttributes, TraceloopSpanKindValues
from opentelemetry import trace
from opentelemetry.trace import get_tracer
from opentelemetry.instrumentation.langchain.version import __version__

# from otel_lib.error_handling import graceful_fallback
import logging
import traceback
from typing import Any, Callable, Iterable, Optional, Type, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])

def graceful_fallback(
    fallback_method: Callable[..., Any], exceptions: Optional[Iterable[Type[BaseException]]] = None
) -> Callable[[F], F]:
    """
    Decorator that reroutes failing functions to a specified fallback method.

    While it is generally not advisable to catch all exceptions, this decorator can be used to
    gracefully degrade a function in situations when raising an error might be too disruptive.
    Exceptions supprssed by this decorator will be logged to the root logger, and all inputs
    to the wrapped function will be passed to the fallback method.


    Args:

    fallback_method (Callable[..., Any]): The fallback method to be called when the wrapped
    function fails.

    exceptions: An optional iterable of exceptions that should be suppressed by this decorator. If
    unset, all exceptions will be suppressed.
    """

    exceptions = (BaseException,) if exceptions is None else tuple(exceptions)

    def decorator(func: F) -> F:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except exceptions as exc:
                msg = (
                    f"Exception occurred in function '{func.__name__}':\n"
                    f"-Args: {args}\n"
                    f"-Kwargs: {kwargs}\n"
                    f"-Exception type: {type(exc).__name__}\n"
                    f"-Exception message: {str(exc)}\n"
                    f"{'*' * 50}\n"
                    f"{traceback.format_exc()}\n"
                    f"{'*' * 50}\n"
                    f"Rerouting to fallback method '{fallback_method.__name__}'"
                )
                logging.error(msg)
            return fallback_method(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


logger = logging.getLogger(__name__)


Message = Dict[str, Any]


# def _langchain_run_type_to_span_kind(run_type: str) -> SpanKind:
#     # TODO: LangChain is moving away from enums and to arbitrary strings
#     # for the run_type variable, so we may need to do the same
#     try:
#         return SpanKind(run_type.upper())
#     except ValueError:
#         return SpanKind.UNKNOWN


def _serialize_json(obj: Any) -> str:
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    return str(obj)


def _prompts(run_inputs: Dict[str, Any]) -> Iterator[Tuple[str, List[str]]]:
    """Yields prompts if present."""
    if "prompts" in run_inputs:
        yield "LLM_PROMPTS", run_inputs["prompts"]


def _otel_input_messages(run_inputs: Dict[str, Any], span):
    """get input messages if present."""

    if len(run_inputs) == 0:
        return
    
    msg_count=0
    if messages := run_inputs.get("messages"):
        for message in messages:
            for item in message:
                if item["id"][-1] == "SystemMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.{msg_count}.system", item["kwargs"].get("content"))
                if item["id"][-1] == "HumanMessage":
                    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.{msg_count}.user", item["kwargs"].get("content"))
        msg_count += 1
    
    if prompts := run_inputs.get("prompts"):
        for prompt in prompts:
            _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.{msg_count}.user", prompt)
        msg_count += 1
    
def _otel_output_messages(run_output: Dict[str, Any], span):
    """get output messages if present."""
    if run_output:
        if len(run_output) == 0:
            return
    else:
        return
    
    msg_count = 0
    if run_output.get("generations"):
        for generate in run_output.get("generations"):
            for item in generate:
                if item.get("text"):
                    _set_span_attribute(span, f"{SpanAttributes.LLM_COMPLETIONS}.{msg_count}", item.get("text"))
        msg_count += 1


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
            yield "LLM_PROMPT_TEMPLATE", template
            yield "LLM_PROMPT_TEMPLATE_VARIABLES", kwargs.get("input_variables", [])
            yield "LLM_PROMPT_TEMPLATE_VERSION", "unknown"
            break


def _params(run_extra: Dict[str, Any], span):
    """set parameters if present."""
    if not (invocation_params := run_extra.get("invocation_params")):
        return
        
    if param := invocation_params.get("model", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, param)
    if param := invocation_params.get("model_name", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, param)
    if invocation_params.get("temperature", None) is not None:
        _set_span_attribute(span, SpanAttributes.LLM_TEMPERATURE, float(invocation_params.get("temperature")))
    if param := invocation_params.get("max_tokens", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MAX_TOKENS, param)
    if param := invocation_params.get("top_p", None):
        _set_span_attribute(span, SpanAttributes.LLM_TOP_P, param)
    if param := invocation_params.get("_type", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_TYPE, param)
        
def _params_watson(run_extra: Dict[str, Any], span):
    """set parameters if present."""
    if not (invocation_params := run_extra.get("invocation_params")):
        return
        
    if param := invocation_params.get("model_id", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, param)
    if param := invocation_params.get("_type", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_TYPE, param)
    if param := invocation_params.get("project_id", None):
        _set_span_attribute(span, SpanAttributes.LLM_REQUEST_PROJECT_ID, param)
        
    if params := invocation_params.get("params"):
        if params.get("temperature", None) is not None:
            _set_span_attribute(span, SpanAttributes.LLM_TEMPERATURE, float(params.get("temperature")))
        if param := params.get("top_p", None):
            _set_span_attribute(span, SpanAttributes.LLM_TOP_P, param)
        if param := params.get("top_k", None):
            _set_span_attribute(span, SpanAttributes.LLM_TOP_K, param)
        if param := params.get("max_new_tokens", None):
            _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MAX_NEW_TOKENS, param)
        if param := params.get("min_new_tokens", None):
            _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MIN_NEW_TOKENS, param)
        if param := params.get("decoding_method", None):
            _set_span_attribute(span, SpanAttributes.LLM_REQUEST_DECODING_METHOD, param)

    return

def _token_counts(run_outputs: Dict[str, Any], span):
    """get token counts if present"""
    if not run_outputs:
        return
    try:
        token_usage = run_outputs["llm_output"]["token_usage"]
    except Exception:
        return
    if token_usage.get("prompt_tokens") is not None:
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_PROMPT_TOKENS, token_usage.get("prompt_tokens"))
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_COMPLETION_TOKENS, token_usage.get("completion_tokens"))
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_TOTAL_TOKENS, token_usage.get("total_tokens"))
    if token_usage.get("generated_token_count") is not None:
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_PROMPT_TOKENS, token_usage.get("input_token_count"))
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_COMPLETION_TOKENS, token_usage.get("generated_token_count"))
        _set_span_attribute(span, SpanAttributes.LLM_USAGE_TOTAL_TOKENS, token_usage.get("input_token_count") + token_usage.get("generated_token_count"))


def _tools(run: Dict[str, Any]) -> Iterator[Tuple[str, str]]:
    """Yields tool attributes if present."""
    if run["run_type"] != "tool":
        return
    run_serialized = run["serialized"]
    if "name" in run_serialized:
        yield "TOOL_NAME", run_serialized["name"]
    if "description" in run_serialized:
        yield "TOOL_DESCRIPTION", run_serialized["description"]


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
        # parent: Optional[Span] = None,
    ) -> None:

        span_kind = (
            "agent"
            if "agent" in run["name"].lower()
            else run["run_type"]
        )
        # (
        #     SpanKind.AGENT
        #     if "agent" in run["name"].lower()
        #     else _langchain_run_type_to_span_kind(run["run_type"])
        # )

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
            _token_counts(run["outputs"], span)
            if span_name == "WatsonxLLM":
                _params_watson(run["extra"], span)
            else:
                _params(run["extra"], span)

            _otel_input_messages(run["inputs"], span)
            _otel_output_messages(run["outputs"], span)
        
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
