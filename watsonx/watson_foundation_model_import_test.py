from datetime import datetime

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

from langfuse import Langfuse
from langfuse.ibm_watson_machine_learning.foundation_models import Model

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

print(generated_response)
