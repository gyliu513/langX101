```console
(py311) guangyaliu@Guangyas-MacBook-Pro-2 watsonx-auto % opentelemetry-instrument \
    --traces_exporter console,otlp \
    --metrics_exporter console \
    --service_name openai-auto-1 \
    --exporter_otlp_endpoint 0.0.0.0:4317 \
    python watsonx-auto.py
Submitting generation request...
```

- Should be a bug, no trace generated.