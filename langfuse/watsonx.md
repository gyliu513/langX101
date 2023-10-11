- vim /Users/guangyaliu/ycliu/lib/python3.10/site-packages/langfuse/callback.py
```python
457             if kwargs["invocation_params"]["_type"] in ["anthropic-llm", "anthropic-chat"]:
458                 model_name = "anthropic"  # unfortunately no model info by anthropic provided.
459             elif kwargs["invocation_params"]["_type"] == "huggingface_hub":
460                 model_name = kwargs["invocation_params"]["repo_id"]
461             elif kwargs["invocation_params"]["_type"] == "azure-openai-chat":
462                 model_name = kwargs["invocation_params"]["model"]
463             elif kwargs["invocation_params"]["_type"] == "llamacpp":
464                 model_name = kwargs["invocation_params"]["model_path"]
465             elif kwargs["invocation_params"]["_type"] == "IBM GENAI":
466                 model_name = kwargs["invocation_params"]["model"]
467                 print(model_name)
```
