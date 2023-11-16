
import sys

# Append the path of the external package to sys.path
sys.path.append('/Users/gyliu/go/src/github.com/gyliu513/langX101/otel/opentelemetry-semantic-conventions-ai')

print(sys.path)

import logging
import os
import types
import pkg_resources
from typing import Collection
from wrapt import wrap_function_wrapper

from opentelemetry import context as context_api
from opentelemetry.trace import get_tracer, SpanKind
from opentelemetry.trace.status import Status, StatusCode

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.utils import (
    _SUPPRESS_INSTRUMENTATION_KEY,
    unwrap,
)

from opentelemetry.semconv.ai import SpanAttributes, LLMRequestTypeValues
from opentelemetry.instrumentation.watsonx.version import __version__

logger = logging.getLogger(__name__)

_instruments = ("ibm_watson_machine_learning >= 1.0.327",)

WRAPPED_METHODS_VERSION_1 = [
    {
        "module": "ibm_watson_machine_learning.foundation_models",
        "object": "Model",
        "method": "generate",
        "span_name": "watsonx.chat",
    },
]

def _set_span_attribute(span, name, value):
    if value is not None:
        if value != "":
            span.set_attribute(name, value)
    return

def _set_api_attributes(span):
    _set_span_attribute(
        span,
        WatsonxSpanAttributes.WATSONX_API_BASE,
        "https://us-south.ml.cloud.ibm.com",
    )
    _set_span_attribute(span, WatsonxSpanAttributes.WATSONX_API_TYPE, "watsonx.ai")
    _set_span_attribute(
        span, WatsonxSpanAttributes.WATSONX_API_VERSION, "1.0"
    )

    return

def _set_input_attributes(span, llm_request_type, instance, kwargs):
    _set_span_attribute(span, SpanAttributes.LLM_REQUEST_MODEL, instance.model_id)
    # Set other attributes
    modelParameters = instance.params
    # need to update opentelemetry.semconv.ai to add Watsonx model parameters.
    # _set_span_attribute(span, SpanAttributes.LLM_DECODING_METHOD, modelParameters.get("decoding_method"))
    _set_span_attribute(span, SpanAttributes.LLM_TEMPERATURE, modelParameters.get("temperature"))
    # _set_span_attribute(span, SpanAttributes.LLM_RANDOM_SEED, modelParameters.get("random_seed"))
    _set_span_attribute(span, SpanAttributes.LLM_TOP_P, modelParameters.get("top_p"))
    _set_span_attribute(span, f"{SpanAttributes.LLM_PROMPTS}.0.user", kwargs.get("prompt"))
    
    return

def _set_response_attributes(span, llm_request_type, response):
    _set_span_attribute(span, SpanAttributes.LLM_RESPONSE_MODEL, response.get("model"))
   # Set other attributes

    usage = response['results'][0]
    _set_span_attribute(
        span, SpanAttributes.LLM_USAGE_TOTAL_TOKENS, usage.get("input_token_count") + usage.get("generated_token_count"),
    )
    _set_span_attribute(
        span,
        SpanAttributes.LLM_USAGE_COMPLETION_TOKENS, usage.get("generated_token_count"),
    )
    _set_span_attribute(
        span, SpanAttributes.LLM_USAGE_PROMPT_TOKENS, usage.get("input_token_count"),
    )

    return

def _with_tracer_wrapper(func):
    """Helper for providing tracer for wrapper functions."""

    def _with_tracer(tracer, to_wrap):
        def wrapper(wrapped, instance, args, kwargs):
            return func(tracer, to_wrap, wrapped, instance, args, kwargs)

        return wrapper

    return _with_tracer

@_with_tracer_wrapper
def _wrap(tracer, to_wrap, wrapped, instance, args, kwargs):
    """Instruments and calls every function defined in TO_WRAP."""
    if context_api.get_value(_SUPPRESS_INSTRUMENTATION_KEY):
        return wrapped(*args, **kwargs)

    name = to_wrap.get("span_name")

    span = tracer.start_span(
        name,
        kind=SpanKind.CLIENT,
        attributes={
            SpanAttributes.LLM_VENDOR: "Watsonx",
            SpanAttributes.LLM_REQUEST_TYPE: "watsonx.ai",
        },
    )

    _set_api_attributes(span)
    _set_input_attributes(span, "watsonx.ai", instance, kwargs)

    response = wrapped(*args, **kwargs)

    _set_response_attributes(span, "watsonx.ai", response)

    span.end()
    return response

class WatsonxSpanAttributes:
    WATSONX_API_VERSION = "watsonx.api_version"
    WATSONX_API_BASE = "watsonx.api_base"
    WATSONX_API_TYPE = "watsonx.api_type"

class WatsonxInstrumentor(BaseInstrumentor):
    """An instrumentor for Watsonx's client library."""

    def instrumentation_dependencies(self) -> Collection[str]:
        return _instruments

    def _instrument(self, **kwargs):
        print("calling instrument")
        tracer_provider = kwargs.get("tracer_provider")
        tracer = get_tracer(__name__, __version__, tracer_provider)

        wrapped_methods = (
            WRAPPED_METHODS_VERSION_1
        )
        for wrapped_method in wrapped_methods:
            wrap_module = wrapped_method.get("module")
            wrap_object = wrapped_method.get("object")
            wrap_method = wrapped_method.get("method")
            wrap_function_wrapper(
                wrap_module,
                f"{wrap_object}.{wrap_method}",
                _wrap(tracer, wrapped_method),
            )

    def _uninstrument(self, **kwargs):
        wrapped_methods = (
            WRAPPED_METHODS_VERSION_1
        )
        for wrapped_method in wrapped_methods:
            wrap_object = wrapped_method.get("object")
            unwrap(f"openai.{wrap_object}", wrapped_method.get("method"))
