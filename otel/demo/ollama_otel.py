"""
Ollama chat completion with OpenTelemetry instrumentation.
Traces exported to Jaeger via OTel Collector (localhost:4317).
Metrics exported to Prometheus via OTel Collector (localhost:4317).
"""

import time
from openai import OpenAI
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

OTEL_ENDPOINT = "http://localhost:4317"
OLLAMA_BASE_URL = "http://localhost:11434/v1"
MODEL = "llama3.2:3b"
SERVICE_NAME = "ollama-chat-demo"

resource = Resource.create({"service.name": SERVICE_NAME})

# Tracer setup
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True))
)
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer(SERVICE_NAME)

# Meter setup
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=True),
    export_interval_millis=5000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter(SERVICE_NAME)

# Instruments
request_counter = meter.create_counter(
    "ollama.chat.requests",
    description="Total number of chat completion requests",
)
latency_histogram = meter.create_histogram(
    "ollama.chat.latency_ms",
    description="Chat completion latency in milliseconds",
    unit="ms",
)
prompt_tokens_counter = meter.create_counter(
    "ollama.chat.prompt_tokens",
    description="Total prompt tokens consumed",
)
completion_tokens_counter = meter.create_counter(
    "ollama.chat.completion_tokens",
    description="Total completion tokens generated",
)

client = OpenAI(api_key="ollama", base_url=OLLAMA_BASE_URL)


def chat(prompt: str) -> str:
    attrs = {"model": MODEL, "prompt_length": len(prompt)}
    with tracer.start_as_current_span("ollama.chat.completion", attributes=attrs) as span:
        start = time.time()
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed_ms = (time.time() - start) * 1000
            content = response.choices[0].message.content

            usage = response.usage
            span.set_attribute("response_length", len(content))
            span.set_attribute("llm.usage.prompt_tokens", usage.prompt_tokens)
            span.set_attribute("llm.usage.completion_tokens", usage.completion_tokens)
            span.set_attribute("llm.usage.total_tokens", usage.total_tokens)
            span.set_attribute("latency_ms", round(elapsed_ms, 2))
            span.set_status(trace.StatusCode.OK)

            request_counter.add(1, attrs)
            latency_histogram.record(elapsed_ms, attrs)
            prompt_tokens_counter.add(usage.prompt_tokens, attrs)
            completion_tokens_counter.add(usage.completion_tokens, attrs)

            return content
        except Exception as exc:
            span.set_status(trace.StatusCode.ERROR, str(exc))
            span.record_exception(exc)
            request_counter.add(1, {**attrs, "error": "true"})
            raise


def main():
    prompts = [
        "What is OpenTelemetry in one sentence?",
        "Name three benefits of distributed tracing.",
        "Explain what Jaeger is used for.",
    ]

    for prompt in prompts:
        print(f"\nPrompt: {prompt}")
        reply = chat(prompt)
        print(f"Reply:  {reply}")

    # Flush metrics before exit
    meter_provider.shutdown()
    tracer_provider.shutdown()
    print("\nDone. Traces visible in Jaeger at http://localhost:16686")
    print("Metrics visible in Prometheus at http://localhost:9090")


if __name__ == "__main__":
    main()
