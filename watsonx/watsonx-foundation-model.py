import threading
import functools
from datetime import datetime

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
import ibm_watson_machine_learning.foundation_models as watson_foundation_models
from ibm_watson_machine_learning.foundation_models import Model

# from genai.credentials import Credentials
# from genai.model import Model
# from genai.schemas import GenerateParams

from langfuse import Langfuse
from langfuse.client import InitialGeneration
from langfuse.api.resources.commons.types.llm_usage import LlmUsage
import tiktoken, os

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

    def count_token(self, message):
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(message))

    def count_token_params(self, params):
        encoding = tiktoken.get_encoding("cl100k_base")
        token_count = 0
        for key, value in params.items():
            token_count += len(encoding.encode(key)) + len(encoding.encode(str(value)))
        return token_count

    def _get_call_details(self, response, api_resource_class, **kwargs):
        name = kwargs.get("name", "Watsonx-generation")
        if name is not None and not isinstance(name, str):
            raise TypeError("name must be a string")

        # trace_id = kwargs.get("trace_id", "Watsonx-generation")
        # if trace_id is not None and not isinstance(trace_id, str):
        #     raise TypeError("trace_id must be a string")

        metadata = kwargs.get("metadata", {})
        if metadata is not None and not isinstance(metadata, dict):
            raise TypeError("metadata must be a dictionary")

        completion = None

        if api_resource_class == Model:
            prompt = kwargs.get("prompt", "")
            completion = response
        else:
            completion = None
            
        watson_model =  self.watson_model
        model = watson_model.model_id
        modelParameters = watson_model.params

        if type(response) is str:
            usage = LlmUsage(prompt_tokens=self.count_token(prompt) +
                self.count_token_params(modelParameters),
                completion_tokens=self.count_token(response))
        else:
            usage = LlmUsage(prompt_tokens = response['results'][0]['input_token_count'],
                completion_tokens = response['results'][0]['generated_token_count'])

        endTime = datetime.now()
        all_details = {
            "status_message": str(response) if isinstance(response, Exception) else None,
            "name": name,
            "prompt": prompt,
            "completion": completion,
            "endTime": endTime,
            "model": model,
            "modelParameters": modelParameters,
            "usage": usage,
            "metadata": metadata,
            "level": "ERROR" if isinstance(response, Exception) else "DEFAULT",
            # "trace_id": trace_id,
        }
        return all_details
        
    def _log_result(self, call_details):
        generation = InitialGeneration(**call_details)
        self.langfuse.generation(generation)

    def langfuse_modified(self, func, api_resource_class):
        self.watson_model = None

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                startTime = datetime.now()
                arg_extractor = CreateArgsExtractor(*args, **kwargs)
                self.watson_model = arg_extractor.get_watsonx_model()
                response = func(*arg_extractor.get_watsonx_args(), **arg_extractor.get_watsonx_kwargs())
                call_details = self._get_call_details(response, api_resource_class, **arg_extractor.get_langfuse_args())
                call_details["startTime"] = startTime
                self._log_result(call_details)
            except Exception as ex:
                call_details = self._get_call_details(ex, api_resource_class, **arg_extractor.get_langfuse_args())
                call_details["startTime"] = startTime
                self._log_result(call_details)
                raise ex

            return response

        return wrapper

    def replace_watson_funcs(self):
        api_resources_classes = [
            (Model, "generate_text"),
            (Model, "generate"),
        ]

        for api_resource_class, method in api_resources_classes:
            create_method = getattr(api_resource_class, method)
            setattr(api_resource_class, method, self.langfuse_modified(create_method, api_resource_class))

        setattr(watson_foundation_models, "flush_langfuse", self.flush)

modifier = WatsonxLangfuse()
modifier.replace_watson_funcs()


def get_credentials(api_key):
    return {
        "url" : "https://us-south.ml.cloud.ibm.com",
        "apikey" : api_key,
    }

iam_api_key = os.environ["IAM_API_KEY"]
project_id = os.environ["PROJECT_ID"]

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

now = datetime.now()
timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
name = "Watsonx-generation-foundation-" + timestamp_str
print("Submitting generation request...")

# generated_response = model.generate_text(
#     name=name, 
#     metadata={"generate_text":"some values"},
#     prompt=prompt_input
#     )

model_id = "meta-llama/llama-2-70b-chat"
parameters = {
    "max_new_tokens": 50,
    "min_new_tokens": 10
}

model = Model(
    model_id = model_id,
    params = parameters,
    credentials=get_credentials(iam_api_key),
    project_id= project_id
    )

prompt_input = "What is the result of 1+1"
generated_response = model.generate(
    name=name, 
    metadata={"generate":"testresult"},
    prompt=prompt_input)

modifier.langfuse.flush()

print(generated_response)
