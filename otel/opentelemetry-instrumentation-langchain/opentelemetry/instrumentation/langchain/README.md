#### clone repo to local env
git clone ssh://git@github.com/gyliu513/langX101

```console
cd langX101/otel/opentelemetry-instrumentation-langchain/opentelemetry/instrumentation/langchain/
```
  
#### install required packages.  
```console
pip install -r requirements.txt  
```

#### update variables in the .env file.  
  
`.env` file:   
  
*Note: The `METRIC_EXPORTER_HTTP_MY_TESTING` is for dev test use only, you can just leave it as it is.*
```bash
PROJECT_ID="xxxxxxxx-xxxx-xxxx"
IBM_GENAI_KEY="xxx-xxxx-xxx"
IBM_GENAI_API="https://bam-api.res.ibm.com"
METRIC_EXPORTER_HTTP_MY_TESTING=""
SVC_NAME="YOUR_SERVICE_NAME"
OTLP_EXPORTER="OTLP_EXPORT_HOST_PORT"
OTEL_EXPORTER_OTLP_INSECURE="true"

### Resource Attributes, see Semantic Conventions for Watsonx AI Metrics
SVC_INSTANCE_ID="SVC_ADRESS:SVC_PORT@SVC_NAME"
LLM_PLATFORM="watsonx"
```

#### Run watson genai with langchain
```console
python watsonx-langchain.py
```
