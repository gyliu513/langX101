###################################################################
#####################This is the test program######################
###################################################################

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

from opentelemetry.instrumentation.watsonx import WatsonxInstrumentor

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
    "decoding_method": "sample",
    "max_new_tokens": 60,
    "min_new_tokens": 10,
    "random_seed": 111,
    "temperature": 0.9,
    "top_k": 50,
    "top_p": 1,
    "repetition_penalty": 2
}

model = Model(
    model_id = model_id,
    params = parameters,
    credentials=get_credentials(iam_api_key),
    project_id= project_id
    )

prompt_input = "What is the result of 1+1"
print(prompt_input)

generated_response = model.generate(prompt=prompt_input)
print(generated_response["results"][0]["generated_text"])
