from dotenv import load_dotenv
import os
load_dotenv()

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
    resource=Resource.create({'service.name': 'my-service-watsonx-2'}),
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

print("Submitting generation request...")

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

with tracer.start_as_current_span("Watsonx_API_Call"):
    generated_response = model.generate(prompt=prompt_input)
    # print(generated_response)
