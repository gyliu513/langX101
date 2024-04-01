from dotenv import load_dotenv
load_dotenv()
import os

from traceloop.sdk import Traceloop

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'

Traceloop.init(app_name="watsonx-langchain")

parameters = {
    "decoding_method": "sample",
    "max_new_tokens": 100,
    "min_new_tokens": 1,
    "temperature": 0.5,
    "top_k": 50,
    "top_p": 1,
}

from langchain_ibm import WatsonxLLM

watsonx_llm = WatsonxLLM(
    model_id="ibm/granite-13b-instruct-v2",
    url="https://us-south.ml.cloud.ibm.com",
    apikey=os.getenv("IAM_API_KEY", None),
    project_id=os.getenv("PROJECT_ID"),
    params=parameters,
)
'''
from langchain.prompts import PromptTemplate

template = "Generate a random question about {topic}: Question: "
prompt = PromptTemplate.from_template(template)

from langchain.chains import LLMChain

llm_chain = LLMChain(prompt=prompt, llm=watsonx_llm)
llm_chain.invoke("dog")
'''

# Calling a single prompt

# watsonx_llm.invoke("Who is man's best friend?")


'''watsonx_llm.generate(
    [
        "The fastest dog in the world?",
        "Describe your chosen dog breed",
    ]
)'''