# run this example
```base
export CHROMA_OTEL_COLLECTION_ENDPOINT="<OpenTelemetry Collector receives endpoint> e.g. http://localhost:4317"
export CHROMA_OTEL_SERVICE_NAME="chromadb-example"
export CHROMA_OTEL_COLLECTION_HEADERS='{"name":"chromadb-example"}'
export CHROMA_OTEL_GRANULARITY="all"

python ./example.py
```