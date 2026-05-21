"""
Ollama chat completion with OpenTelemetry AUTO instrumentation.

Run with:
  export OTEL_SERVICE_NAME=ollama-chat-auto
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
  export OTEL_TRACES_EXPORTER=otlp
  export OTEL_METRICS_EXPORTER=otlp
  .venv/bin/opentelemetry-instrument python ollama_otel_auto.py
"""

from openai import OpenAI

client = OpenAI(api_key="ollama", base_url="http://localhost:11434/v1")


def chat(prompt: str) -> str:
    response = client.chat.completions.create(
        model="llama3.2:3b",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


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

    print("\nDone. Traces visible in Jaeger at http://localhost:16686")
    print("Metrics visible in Prometheus at http://localhost:9090")


if __name__ == "__main__":
    main()
