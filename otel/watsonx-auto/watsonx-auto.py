from dotenv import load_dotenv
import os
load_dotenv()

from ibm_watson_machine_learning.foundation_models import Model

def get_credentials(api_key):
    return {
        "url" : "https://us-south.ml.cloud.ibm.com",
        "apikey" : api_key,
    }

iam_api_key = os.environ["IAM_API_KEY"]
project_id = os.environ["PROJECT_ID"]

prompt_input = """Calculate result

Input:
what is the capital of China.

Output:
"""

print("Submitting generation request...")

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
generated_response = model.generate(prompt=prompt_input)
# print(generated_response)
