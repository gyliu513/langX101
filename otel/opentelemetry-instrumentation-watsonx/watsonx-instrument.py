
import logging
import os
import types
import pkg_resources
from typing import Collection
from wrapt import wrap_function_wrapper
import openai

from opentelemetry import context as context_api
from opentelemetry.trace import get_tracer, SpanKind
from opentelemetry.trace.status import Status, StatusCode

from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.utils import (
    _SUPPRESS_INSTRUMENTATION_KEY,
    unwrap,
)

from opentelemetry.semconv.ai import SpanAttributes, LLMRequestTypeValues
from opentelemetry.instrumentation.openai.version import __version__

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

    response = wrapped(*args, **kwargs)

    span.end()
    return response

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


from dotenv import load_dotenv
import os
load_dotenv()

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'

from ibm_watson_machine_learning.foundation_models import Model

from opentelemetry import trace
from opentelemetry.instrumentation.wsgi import collect_request_attributes
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.trace import (
    SpanKind,
    get_tracer_provider,
    set_tracer_provider,
)

tracer_provider = TracerProvider(
    resource=Resource.create({'service.name': 'my-service-watsonx-12'}),
)

# Create an OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(
    endpoint="0.0.0.0:4317",  # Replace with your OTLP endpoint URL
)

# Add the exporter to the TracerProvider
# tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))  # Add any span processors you need
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

# Register the TracerProvider
trace.set_tracer_provider(tracer_provider)

WatsonxInstrumentor().instrument(tracer_provider=tracer_provider)

def get_credentials(api_key):
    return {
        "url" : "https://us-south.ml.cloud.ibm.com",
        "apikey" : api_key,
    }

iam_api_key = os.environ["IAM_API_KEY"]
project_id = os.environ["PROJECT_ID"]

prompt_input = """Calculate result

Input:
what is the capital of China.

Output:
"""

model_id = "meta-llama/llama-2-70b-chat"
parameters = {
    "max_new_tokens": 50,
    "min_new_tokens": 10
}

model = Model(
    model_id = model_id,
    params = parameters,
    credentials=get_credentials(iam_api_key),
    project_id= project_id
    )

prompt_input = "What is the result of 1+1"

generated_response = model.generate(prompt=prompt_input)
# print(generated_response)
