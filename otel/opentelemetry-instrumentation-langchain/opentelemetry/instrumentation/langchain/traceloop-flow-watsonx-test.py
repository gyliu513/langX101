import types
from openai import OpenAI
from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow

from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as WatsonMLGenParams
from dotenv import load_dotenv, find_dotenv
import os
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames
from ibm_watsonx_ai.foundation_models import ModelInference

from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as WatsonMLGenParams
from ibm_watson_machine_learning.foundation_models import Model as ML_Model
from ibm_watson_machine_learning.client import APIClient

from genai.extensions.langchain import LangChainInterface
from genai.schemas import GenerateParams as GenaiGenerateParams
from genai.credentials import Credentials
from genai import Model as Model_genai


from pprint import pprint
# from genai.credentials import Credentials
# from ibm_watsonx_ai.credentials import Credentials
from ibm_watsonx_ai import APIClient
load_dotenv(find_dotenv())


# Traceloop.init(app_name="joke_generation_service")
# os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'
# os.environ['OTEL_PYTHON_EXCLUDED_URLS']="/oidc,/ml/v1-beta,api.dataplatform.cloud.ibm.com"
Traceloop.init(api_endpoint=os.environ["OTLP_EXPORTER_HTTP"],
            #    api_key=os.environ["TRACELOOP_API_KEY"],
               app_name="traceloop-flow-watsonx-ai-0223",
               )

@workflow(name="joke_creation")
def create_joke():   
    client = OpenAI(
        # This is the default and can be omitted
        api_key=os.environ.get("OPENAI_API_KEY"),
    )
    print(os.environ.get("OPENAI_API_KEY"))
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": "tell me a joke",
            }
        ],
        model="gpt-3.5-turbo",
    )
    pprint(chat_completion)


def test_watson_ai_init() -> ModelInference:
    os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")
    api_key = os.getenv("IAM_API_KEY", None) 
    api_url = "https://us-south.ml.cloud.ibm.com"
    # creds = Credentials(api_key, api_endpoint=api_url)
    #_______________________________________   

    watson_ml_credentials = {
                "apikey":api_key,
                "url": api_url
                }

    # api_client = APIClient(wml_credentials)    
    
    watson_ai_parameters = {
        GenTextParamsMetaNames.DECODING_METHOD: "sample",
        GenTextParamsMetaNames.MAX_NEW_TOKENS: 100,
        GenTextParamsMetaNames.MIN_NEW_TOKENS: 1,
        GenTextParamsMetaNames.TEMPERATURE: 0.5,
        GenTextParamsMetaNames.TOP_K: 50,
        GenTextParamsMetaNames.TOP_P: 1,
    }
    
    watsonx_ai_model = ModelInference(
        model_id="google/flan-ul2",
        # model_id="ibm/granite-13b-chat-v1",
        project_id=os.getenv("PROJECT_ID"),
        params=watson_ai_parameters,
        credentials=watson_ml_credentials,
        # api_client=api_client,
    )
    return watsonx_ai_model


@workflow(name="simple_watson_ai_question")
def test_watson_ai_generate(question):
    watsonx_ai_model = test_watson_ai_init()
    return watsonx_ai_model.generate(prompt=question)


@workflow(name="simple_watson_ai_question")
def test_watson_ai_generate_stream(question):
    watsonx_ai_model = test_watson_ai_init()    
    return watsonx_ai_model.generate_text_stream(prompt=question)


def test_watson_ml_model_init() -> ML_Model:
    
    watson_ml_parameters = {
        WatsonMLGenParams.DECODING_METHOD: "sample",
        WatsonMLGenParams.MAX_NEW_TOKENS: 30,
        WatsonMLGenParams.MIN_NEW_TOKENS: 1,
        WatsonMLGenParams.TEMPERATURE: 0.5,
        WatsonMLGenParams.TOP_K: 50,
        WatsonMLGenParams.TOP_P: 1,
    }

    # from langchain.llms import WatsonxLLM
    os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")
    api_key = os.getenv("IAM_API_KEY", None) 
    api_url = "https://us-south.ml.cloud.ibm.com"
    # creds = Credentials(api_key, api_endpoint=api_url)

    watson_ml_credentials = {
                    "apikey":api_key,
                    "url": api_url
    }

    # from ibm_watson_machine_learning import APIClient
    # wml_client = APIClient(wml_credentials)

    watsonx_ml_model = ML_Model(
        model_id="google/flan-ul2",
        # url=api_url,
        project_id=os.getenv("PROJECT_ID"),
        params=watson_ml_parameters,
        credentials=watson_ml_credentials,
    )

    return watsonx_ml_model


@workflow(name="simple_watson_ml_question")
def test_watson_ml_generate_text(question):
    watsonx_ml_model = test_watson_ml_model_init()
    return watsonx_ml_model.generate_text(prompt=question)
    

@workflow(name="simple_watson_ml_question")
def test_watson_ml_generate_text_stream(question):
    watsonx_ml_model = test_watson_ml_model_init()
    return watsonx_ml_model.generate_text_stream(prompt=question)


question_multiple_responses = ["What is 1 + 1?","what is the result of 3 + 3?"]
question_normal = "what is the most famous tourist attraction in Italy"
question_simple = "What is 1 + 1?"
question_stream = "Write an epigram about the sun"

response = test_watson_ai_generate(question_simple)

# response = test_watson_ai_generate_stream(question_stream)

if isinstance(response, types.GeneratorType):
    for chunk in response:
        print(chunk, end='')
else:
    pprint(response)
