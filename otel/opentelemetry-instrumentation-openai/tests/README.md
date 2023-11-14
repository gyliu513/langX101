<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Run OTEL Collector](#run-otel-collector)
- [Install OTEL Packages](#install-otel-packages)
- [ignore SSL errors](#ignore-ssl-errors)
- [Run the openai script](#run-the-openai-script)
- [Check Jaeger UI](#check-jaeger-ui)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

## Run OTEL Collector

- goto https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/examples/demo and run the collector via `docker compose up -d`

## Install OTEL Packages

```
pip install opentelemetry-distro
opentelemetry-bootstrap -a install
pip install opentelemetry-exporter-otlp
```

## ignore SSL errors

```
export OTEL_EXPORTER_OTLP_INSECURE=true
```

## Run the openai script
```console
(py311) guangyaliu@Guangyas-MacBook-Pro-2 tests % python openai-instrument.py
calling instrument
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
ChatCompletion(id='chatcmpl-8KsKLRaePBYVpkkLM6QUcgEORMQsH', choices=[Choice(finish_reason='stop', index=0, message=ChatCompletionMessage(content='This is a test.', role='assistant', function_call=None, tool_calls=None))], created=1699986085, model='gpt-3.5-turbo-0613', object='chat.completion', system_fingerprint=None, usage=CompletionUsage(completion_tokens=5, prompt_tokens=12, total_tokens=17))
```

## Check Jaeger UI

![](images/openai-otel-jaeger.png)