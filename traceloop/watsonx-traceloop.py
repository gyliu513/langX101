import os
import types
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames
from ibm_watsonx_ai.foundation_models import ModelInference
from pprint import pprint
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow

from dotenv import load_dotenv
load_dotenv()

Traceloop.init(app_name="watsonx-ai-app")


def watson_ai_init() -> ModelInference:
    api_key = os.getenv("WATSONX_API_KEY", None)
    api_url = "https://us-south.ml.cloud.ibm.com"

    watson_ml_credentials = {
        "apikey": api_key,
        "url": api_url
    }

    watson_ai_parameters = {
        GenTextParamsMetaNames.DECODING_METHOD: "sample",
        GenTextParamsMetaNames.MAX_NEW_TOKENS: 100,
        GenTextParamsMetaNames.MIN_NEW_TOKENS: 1,
        GenTextParamsMetaNames.TEMPERATURE: 0.5,
        GenTextParamsMetaNames.TOP_K: 50,
        GenTextParamsMetaNames.TOP_P: 1,
    }

    watsonx_ai_model = ModelInference(
        model_id="ibm/granite-13b-chat-v2",
        project_id=os.getenv("WATSONX_PROJECT_ID"),
        params=watson_ai_parameters,
        credentials=watson_ml_credentials
    )
    return watsonx_ai_model


@workflow(name="watsox_ai_workflow")
def watson_ai_generate(question):
    watsonx_ai_model = watson_ai_init()
    return watsonx_ai_model.generate(prompt=question)


question_simple = "Tell me something about IBM"

response = watson_ai_generate(question_simple)

if isinstance(response, types.GeneratorType):
    for chunk in response:
        print(chunk, end='')

pprint(response)