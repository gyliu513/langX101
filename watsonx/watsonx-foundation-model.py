import threading
import functools
from datetime import datetime

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
from ibm_watson_machine_learning.foundation_models import Model

# from genai.credentials import Credentials
# from genai.model import Model
# from genai.schemas import GenerateParams

from langfuse import Langfuse
from langfuse.client import InitialGeneration
from langfuse.api.resources.commons.types.llm_usage import LlmUsage

class CreateArgsExtractor:
    def __init__(self, name=None, metadata=None, trace_id=None, **kwargs):
        self.args = {}
        # self.args["name"] = name
        # self.args["metadata"] = metadata
        # self.args["trace_id"] = trace_id
        self.kwargs = kwargs  # {"prompts": metadata}

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
        name = "Watsonx-generation-foundation-" + timestamp_str

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
            completion = "oooooook"
        else:
            completion = None

        model = "google/flan-ul2"
        # model = kwargs.get("model", None) if isinstance(result, Exception) else result.model

        usage = None
        # usage = None if isinstance(result, Exception) or result.usage is None else LlmUsage(**result.usage)
        endTime = datetime.now()
        
        all_details = {
            "status_message": str(result) if isinstance(result, Exception) else None,
            "name": name,
            "prompt": "What is 1 + 1?",
            "completion": completion,
            "endTime": endTime,
            "model": model,
            "modelParameters": "",
            "usage": usage,
            "metadata": metadata,
            "level": "ERROR" if isinstance(result, Exception) else "DEFAULT",
            # "trace_id": trace_id,
        }
        return all_details

    def _log_result(self, call_details):
        generation = InitialGeneration(**call_details)
        self.langfuse.generation(generation)

    def instrument_method(self, cls, method_name):
        method = getattr(cls, method_name)

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            print(f"Before calling {method.__name__}")
            arg_extractor = CreateArgsExtractor(*args, **kwargs)
            startTime = datetime.now()
            result = method(*args, **kwargs)
            print(f"After calling {method.__name__}")
            call_details = self._get_call_details(result, cls, **arg_extractor.get_langfuse_args())
            call_details["startTime"] = startTime
            self._log_result(call_details)
            
            
            return result

        setattr(cls, method_name, wrapper)

'''
    def langfuse_modified(self, func, api_resource_class):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                arg_extractor = CreateArgsExtractor(*args, **kwargs)
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

    def replace_watsonx_funcs(self):
        api_resources_classes = [
            (Model, "generate"),
        ]

        for api_resource_class, method in api_resources_classes:
            generate_method = getattr(api_resource_class, method)
            setattr(api_resource_class, method, self.langfuse_modified(generate_method, api_resource_class))
'''

'''
def instrument_method(cls, method_name):
    method = getattr(cls, method_name)

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        print(f"Before calling {method.__name__}")
        result = method(*args, **kwargs)
        print(f"After calling {method.__name__}")
        return result

    setattr(cls, method_name, wrapper)

# Instrument the 'display' method of the SimpleClass
instrument_method(SimpleClass, 'display')
'''



modifier = WatsonxLangfuse()
modifier.instrument_method(Model, "generate_text")

import os

def get_credentials(api_key):
    return {
        "url" : "https://us-south.ml.cloud.ibm.com",
        "apikey" : api_key,
    }

iam_api_key = os.environ["IAM_API_KEY"]
project_id = os.environ["PROJECT_ID"]
print(project_id)

model_id = "google/flan-ul2"

parameters = {
    "decoding_method": "sample",
    "max_new_tokens": 200,
    "min_new_tokens": 50,
    "random_seed": 111,
    "temperature": 0.8,
    "top_k": 50,
    "top_p": 1,
    "repetition_penalty": 2
}

model = Model(
    model_id = model_id,
    params = parameters,
    credentials = get_credentials(iam_api_key),
    project_id = project_id
    )

prompt_input = """Calculate result

Input:
what is the capital of China.

Output:
"""

print("Submitting generation request...")
generated_response = model.generate_text(prompt=prompt_input)
print(generated_response)

"""
Output:
Submitting generation request...
Before calling generate_text
After calling generate_text
generate
We are thrilled to have you on our team! Thank you so much for participating in the codefest. There were lots of great ideas that came out of the discussions, and we'll definitely be looking into many of them during our ongoing work on X11. Please feel free to reach out to me with any questions or thoughts you might have about other projects or events at Enron Labs. I look forward to working with you further. Sincerely,
"""