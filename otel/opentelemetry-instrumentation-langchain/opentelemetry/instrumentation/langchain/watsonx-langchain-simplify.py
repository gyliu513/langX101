# import logging
# import sys
from dotenv import load_dotenv, find_dotenv
import os
load_dotenv(find_dotenv())

""" only need 2 lines code to instrument Langchain LLM
"""

from otel_lib.instrumentor_simplify import LangChainHandlerInstrumentor as SimplifiedLangChainHandlerInstrumentor
tracer_provider, metric_provider = SimplifiedLangChainHandlerInstrumentor().instrument(
    otlp_endpoint=os.environ["OTLP_EXPORTER"]+":4317",
    metric_endpoint=os.environ["OTLP_EXPORTER"]+":4317",
    service_name="my-service-0111a",
    insecure = True,
    )
"""=======================================================
"""



from otel_lib.country_name import RandomCountryName
os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")

from genai.extensions.langchain import LangChainInterface
from genai.schemas import GenerateParams as GenaiGenerateParams
from genai.credentials import Credentials

api_key = os.getenv("IBM_GENAI_KEY", None) 
api_url = "https://bam-api.res.ibm.com"
creds = Credentials(api_key, api_endpoint=api_url)

genai_parameters = GenaiGenerateParams(
    decoding_method="sample",  # Literal['greedy', 'sample']
    max_new_tokens=300,
    min_new_tokens=10,
    top_p=1,
    top_k=50,
    temperature=0.05,
    time_limit=30000,
    truncate_input_tokens=2048,
)

watsonx_genai_llm = LangChainInterface(
    model = "ibm/granite-13b-chat-v1",
    params=genai_parameters, 
    credentials=creds
)

def langchain_watson_genai_llm_chain():
    from langchain.schema import SystemMessage, HumanMessage
    from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
    from langchain.chains import LLMChain, SequentialChain
    
    first_prompt_messages = [
        SystemMessage(content="answer the question with very short answer, as short as you can."),
        # HumanMessage(content=f"tell me what is the most famous tourist attraction in the capital city of {RandomCountryName()}?"),
        HumanMessage(content=f"tell me what is the most famous dish in {RandomCountryName()}?"),
    ]
    first_prompt_template = ChatPromptTemplate.from_messages(first_prompt_messages)
    first_chain = LLMChain(llm=watsonx_genai_llm, prompt=first_prompt_template, output_key="target")

    second_prompt_messages = [
        SystemMessage(content="answer the question with very brief answer."),
        # HumanMessagePromptTemplate.from_template("how to get to {target} from the nearest airport by public transportation?\n "),
        HumanMessagePromptTemplate.from_template("pls provide the recipe for dish {target}\n "),
    ]
    second_prompt_template = ChatPromptTemplate.from_messages(second_prompt_messages)
    second_chain = LLMChain(llm=watsonx_genai_llm, prompt=second_prompt_template)

    workflow = SequentialChain(chains=[first_chain, second_chain], input_variables=[])
    print(workflow({}))
    
# print(watsonx_genai_llm(f"what is the capital city of {RandomCountryName()}?"))


langchain_watson_genai_llm_chain()

# metric_provider.force_flush()