import threading
import functools
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

from genai.credentials import Credentials
from genai.model import Model
from genai.schemas import GenerateParams

from langfuse import Langfuse
from langfuse.client import InitialGeneration
from langfuse.api.resources.commons.types.llm_usage import LlmUsage

class CreateArgsExtractor:
    def __init__(self, name=None, metadata=None, trace_id=None, **kwargs):
        self.args = {}
        # self.args["name"] = name
        # self.args["metadata"] = metadata
        # self.args["trace_id"] = trace_id
        self.kwargs = {"prompts": metadata}

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
        # name = kwargs.get("name", "Watsonx-generation")
        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        name = "Watsonx-generation" + timestamp_str

        if name is not None and not isinstance(name, str):
            raise TypeError("name must be a string")

        trace_id = kwargs.get("trace_id", "Watsonx-generation")
        if trace_id is not None and not isinstance(trace_id, str):
            raise TypeError("trace_id must be a string")

        # metadata = kwargs.get("metadata", {})
        metadata = {}

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
                bob_params = GenerateParams(
                    decoding_method="sample",
                    max_new_tokens=25,
                    min_new_tokens=1,
                    stream=False,
                    temperature=1,
                    top_k=50,
                    top_p=1,
                )

                creds = Credentials(api_key, api_endpoint)
                bob_model = Model("google/flan-ul2", params=bob_params, credentials=creds)
                startTime = datetime.now()
                arg_extractor = CreateArgsExtractor(*args, **kwargs)
                alice_q = "What is 1 + 1?"
                aliceq = [alice_q]
                # result = bob_model.func(prompts=aliceq)
                result = func(api_resource_class, prompts=aliceq)
                # result = func(**arg_extractor.get_watsonx_args())
                call_details = self._get_call_details(result, api_resource_class, **arg_extractor.get_langfuse_args())
                call_details["startTime"] = startTime
                self._log_result(call_details)
            except Exception as ex:
                # call_details = self._get_call_details(ex, api_resource_class, **arg_extractor.get_langfuse_args())
                # call_details["startTime"] = startTime
                # self._log_result(call_details)
                raise ex

            return result

        return wrapper

    '''
    Question/Issue: generate is not a class method like openai, how to modify this function??
    '''
    def replace_watsonx_funcs(self):
        api_resources_classes = [
            (Model, "generate"),
        ]

        for api_resource_class, method in api_resources_classes:
            generate_method = getattr(api_resource_class, method)
            setattr(api_resource_class, method, self.langfuse_modified(generate_method, api_resource_class))

modifier = WatsonxLangfuse()
modifier.replace_watsonx_funcs()

import os

api_key = os.getenv("GENAI_KEY", None)
api_endpoint = os.getenv("GENAI_API", None)

bob_params = GenerateParams(
    decoding_method="sample",
    max_new_tokens=25,
    min_new_tokens=1,
    stream=False,
    temperature=1,
    top_k=50,
    top_p=1,
)

creds = Credentials(api_key, api_endpoint)
bob_model = Model("google/flan-ul2", params=bob_params, credentials=creds)

alice_q = "What is 1 + 1?"
print(f"[Alice][Q] {alice_q}")


bob_response = bob_model.generate([alice_q])
bob_a = bob_response[0].generated_text
print(f"[Bob][A] {bob_a}")