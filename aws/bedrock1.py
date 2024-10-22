'''
Put following parameter to a .env file

TRACELOOP_API_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
'''

from dotenv import load_dotenv
load_dotenv()

import boto3
import json

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

# Traceloop.init(app_name="joke_generation_service")
bedrock_runtime = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")


@task(name="gyliu_joke_creation")
def create_joke():

    express_prompt = "Tell me a joke"

    body = json.dumps({
        "inputText": express_prompt, 
        "textGenerationConfig":{  
            "maxTokenCount":128,
            "stopSequences":[], #define phrases that signal the model to conclude text generation.
            "temperature":0, #Temperature controls randomness; higher values increase diversity, lower values boost predictability.
            "topP":0.9 # Top P is a text generation technique, sampling from the most probable tokens in a distribution.
        }
    })

    response = bedrock_runtime.invoke_model(
        body=body,
        modelId="amazon.titan-text-express-v1",
        accept="application/json", 
        contentType="application/json"
    )

    response_body = json.loads(response.get('body').read())
    outputText = response_body.get('results')[0].get('outputText')

    text = outputText[outputText.index('\n')+1:]
    about_lambda = text.strip()
    return about_lambda

@workflow(name="gyliu_joke_generator")
def joke_workflow():
    print(create_joke())


joke_workflow()
