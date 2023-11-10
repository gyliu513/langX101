from dotenv import load_dotenv
import os
load_dotenv()

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
    resource=Resource.create({'service.name': 'my-service-openai-2'}),
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

tracer = trace.get_tracer_provider().get_tracer(__name__)

from openai import OpenAI

with tracer.start_as_current_span("OpenAI_API_Call"):

    client = OpenAI(
        # defaults to os.environ.get("OPENAI_API_KEY")
        api_key=os.getenv("OPENAI_API_KEY"),
    )

    chat_completion = client.chat.completions.create(
        messages=[
           {
                "role": "user",
                "content": "Say this is a test",
            }
        ],
        model="gpt-3.5-turbo",
    )

