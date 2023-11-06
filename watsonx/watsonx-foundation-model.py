import threading
import functools
from datetime import datetime

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
import ibm_watson_machine_learning.foundation_models as watsonf
from ibm_watson_machine_learning.foundation_models import Model

# from genai.credentials import Credentials
# from genai.model import Model
# from genai.schemas import GenerateParams

from langfuse import Langfuse
from langfuse.client import InitialGeneration
from langfuse.api.resources.commons.types.llm_usage import LlmUsage
import tiktoken

class CreateArgsExtractor:
    def __init__(self, watson_model=None, name=None, metadata=None, **kwargs):
        self.args = {}
        self.watson_model = watson_model
        self.args["name"] = name
        self.args["metadata"] = metadata
        self.kwargs = kwargs

    def get_langfuse_args(self):
        return {**self.args, **self.kwargs}

    def get_watsonx_kwargs(self):
        return self.kwargs

    def get_watsonx_args(self):
        return (self.watson_model,)

    def get_watsonx_model(self):
        return self.watson_model

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

    # count plain text prompt and result
    # need to further investigate watsonx model token count rules.
    def count_token(self, message):
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(message))

    def count_token_params(self, params):
        encoding = tiktoken.get_encoding("cl100k_base")
        token_count = 0
        for key, value in params.items():
            token_count += len(encoding.encode(key)) + len(encoding.encode(str(value)))
        return token_count

    def _get_call_details(self, result, api_resource_class, **kwargs):
        name = kwargs.get("name", "Watsonx-generation")
        if name is not None and not isinstance(name, str):
            raise TypeError("name must be a string")

        # trace_id = kwargs.get("trace_id", "Watsonx-generation")
        # if trace_id is not None and not isinstance(trace_id, str):
        #     raise TypeError("trace_id must be a string")

        metadata = kwargs.get("metadata", {})
        #metadata = {}

        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")

        completion = None

        if api_resource_class == Model:
            prompt = kwargs.get("prompt", "")
            completion = result
        else:
            completion = None
        watson_model =  self.watson_model
        model = watson_model.model_id
        modelParameters = watson_model.params
        #model = "google/flan-ul2"
        # model = kwargs.get("model", None) if isinstance(result, Exception) else result.model

        
        usage = LlmUsage(prompt_tokens=self.count_token(prompt) +
            self.count_token_params(modelParameters),
            completion_tokens=self.count_token(result))
        # usage = None if isinstance(result, Exception) or result.usage is None else LlmUsage(**result.usage)
        endTime = datetime.now()
        # modelParameters = {
        #     "temperature": kwargs.get("temperature", 1),
        #     "maxTokens": kwargs.get("max_tokens", float("inf")),
        #     "top_p": kwargs.get("top_p", 1),
        #     "frequency_penalty": kwargs.get("frequency_penalty", 0),
        #     "presence_penalty": kwargs.get("presence_penalty", 0),
        # }        
        all_details = {
            "status_message": str(result) if isinstance(result, Exception) else None,
            "name": name,
            "prompt": prompt,
            "completion": completion,
            "endTime": endTime,
            "model": model,
            "modelParameters": modelParameters,
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
        self.watson_model = None

        @functools.wraps(method)
        def wrapper(*args, **kwargs):
            print(f"Before calling {method.__name__}")
            arg_extractor = CreateArgsExtractor(*args, **kwargs)
            self.watson_model = arg_extractor.get_watsonx_model()
            startTime = datetime.now()
            result = method(*arg_extractor.get_watsonx_args(), **arg_extractor.get_watsonx_kwargs())
            print(f"After calling {method.__name__}")
            call_details = self._get_call_details(result, cls, **arg_extractor.get_langfuse_args())
            call_details["startTime"] = startTime
            self._log_result(call_details)
            
            return result

        setattr(cls, method_name, wrapper)
        setattr(watsonf, "flush_langfuse", self.flush)

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
    "temperature": 0.9,
    "top_k": 50,
    "top_p": 1,
    "repetition_penalty": 2
}

model = watsonf.Model(
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

now = datetime.now()
timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
name = "Watsonx-generation-foundation-" + timestamp_str
print("Submitting generation request...")

generated_response = model.generate_text(
    name=name, 
    metadata={"metakey":"some values"},
    prompt=prompt_input
    )

modifier.langfuse.flush()

print(generated_response)
