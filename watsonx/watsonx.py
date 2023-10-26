import threading
import functools
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

'''
import openai
from openai.api_resources import ChatCompletion, Completion
'''

from genai.credentials import Credentials
from genai.model import Model
from genai.schemas import GenerateParams

from langfuse import Langfuse
from langfuse.client import InitialGeneration
from langfuse.api.resources.commons.types.llm_usage import LlmUsage

class CreateArgsExtractor:
    def __init__(self, name=None, metadata=None, trace_id=None, **kwargs):
        self.args = {}
        self.args["name"] = name
        self.args["metadata"] = metadata
        self.args["trace_id"] = trace_id
        self.kwargs = kwargs

    def get_langfuse_args(self):
        return {**self.args, **self.kwargs}

    def get_watsonx_args(self):
        return self.kwargs


class WatsonxLangfuse:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(WatsonxLangfuse, cls).__new__(cls)
                    cls._instance.initialize()
        return cls._instance

    def initialize(self):
        self.langfuse = Langfuse()

    @classmethod
    def flush(cls):
        cls._instance.langfuse.flush()

    def _get_call_details(self, result, api_resource_class, **kwargs):
        name = kwargs.get("name", "Watsonx-generation")

        if name is not None and not isinstance(name, str):
            raise TypeError("name must be a string")

        trace_id = kwargs.get("trace_id", "Watsonx-generation")
        if trace_id is not None and not isinstance(trace_id, str):
            raise TypeError("trace_id must be a string")

        metadata = kwargs.get("metadata", {})

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")

        completion = None

        if api_resource_class == Model:
            print("generate")
        else:
            completion = None

        model = kwargs.get("model", None) if isinstance(result, Exception) else result.model

        usage = None if isinstance(result, Exception) or result.usage is None else LlmUsage(**result.usage)
        endTime = datetime.now()
        
        all_details = {
            "status_message": str(result) if isinstance(result, Exception) else None,
            "name": name,
            "prompt": "xxx",
            "completion": completion,
            "endTime": endTime,
            "model": model,
            "modelParameters": "",
            "usage": usage,
            "metadata": metadata,
            "level": "ERROR" if isinstance(result, Exception) else "DEFAULT",
            "trace_id": trace_id,
        }
        return all_details

    def _log_result(self, call_details):
        generation = InitialGeneration(**call_details)
        self.langfuse.generation(generation)

    def langfuse_modified(self, func, api_resource_class):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                startTime = datetime.now()
                arg_extractor = CreateArgsExtractor(*args, **kwargs)
                result = func(**arg_extractor.get_openai_args())
                call_details = self._get_call_details(result, api_resource_class, **arg_extractor.get_langfuse_args())
                call_details["startTime"] = startTime
                self._log_result(call_details)
            except Exception as ex:
                call_details = self._get_call_details(ex, api_resource_class, **arg_extractor.get_langfuse_args())
                call_details["startTime"] = startTime
                self._log_result(call_details)
                raise ex

            return result

        return wrapper

    def replace_watsonx_funcs(self):
        api_resources_classes = [
            (Model, "generate"),
        ]

        for api_resource_class, method in api_resources_classes:
            create_method = getattr(api_resource_class, method)
            setattr(api_resource_class, method, self.langfuse_modified(create_method, api_resource_class))

modifier = WatsonxLangfuse()
modifier.replace_watsonx_funcs()