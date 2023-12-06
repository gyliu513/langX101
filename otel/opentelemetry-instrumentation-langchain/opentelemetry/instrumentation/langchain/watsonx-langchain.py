"""Langchain BaseHandler instrumentation"""
import logging
from typing import Collection

from opentelemetry.trace import get_tracer
from opentelemetry.instrumentation.langchain.version import __version__
from opentelemetry.semconv.ai import TraceloopSpanKindValues
from otel_lib.instrumentor import LangChainHandlerInstrumentor


logger = logging.getLogger(__name__)

_instruments = ("langchain >= 0.0.200",)


from dotenv import load_dotenv, find_dotenv
import os
load_dotenv(find_dotenv())

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'

import sys

from opentelemetry import trace
# from opentelemetry.instrumentation.wsgi import collect_request_attributes
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
    resource=Resource.create({'service.name': os.environ["SVC_NAME"]}),
)

# Create an OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(
    endpoint=os.environ["OTLP_EXPORTER"]+":4317",  # Replace with your OTLP endpoint URL
)

# Add the exporter to the TracerProvider
# tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))  # Add any span processors you need
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

# Register the TracerProvider
trace.set_tracer_provider(tracer_provider)

LangChainHandlerInstrumentor().instrument(tracer_provider=tracer_provider)

from dotenv import load_dotenv
import os
load_dotenv()

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'

os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")

from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams

parameters = {
    GenParams.DECODING_METHOD: "sample",
    GenParams.MAX_NEW_TOKENS: 30,
    GenParams.MIN_NEW_TOKENS: 1,
    GenParams.TEMPERATURE: 0.5,
    GenParams.TOP_K: 50,
    GenParams.TOP_P: 1,
}

from langchain.llms import WatsonxLLM

watsonx_llm = WatsonxLLM(
    model_id="google/flan-ul2",
    url="https://us-south.ml.cloud.ibm.com",
    project_id=os.getenv("PROJECT_ID"),
    params=parameters,
)

from langchain.prompts import PromptTemplate

template = "Generate a random question about {topic}: Question: "
prompt = PromptTemplate.from_template(template)

from langchain.chains import LLMChain

llm_chain = LLMChain(prompt=prompt, llm=watsonx_llm)
llm_chain.run("dog")

