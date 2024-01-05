#### clone repo to local env
git clone ssh://git@github.com/gyliu513/langX101

```console
cd langX101/otel/opentelemetry-instrumentation-langchain/opentelemetry/instrumentation/langchain/
```
  
#### update variables in the .env file.  
  
`.env` file:   
```bash
PROJECT_ID="xxxxxxxx-xxxx-xxxx"
IBM_GENAI_KEY="xxx-xxxx-xxx"
IBM_GENAI_API="https://bam-api.res.ibm.com"
SVC_NAME="YOUR_SERVICE_NAME"
OTLP_EXPORTER="OTLP_EXPORT_HOST_PORT"
METRIC_EXPORTER_HTTP_TESTING2="http://mymetric_export_url:8000/v1/metrics"
OTEL_EXPORTER_OTLP_INSECURE="true"
```

#### Run watson genai with langchain
```console
python watsonx-langchain.py
```
