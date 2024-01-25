from dotenv import load_dotenv, find_dotenv
import os

from genai.extensions.langchain import LangChainInterface
from genai.schemas import GenerateParams as GenaiGenerateParams
from genai.credentials import Credentials
# from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as WatsonMLGenParams
from ibm_watsonx_ai.metanames import GenTextParamsMetaNames
# from ibm_watsonx_ai.foundation_models import ModelInference

from langchain.llms.openai import OpenAI
from langchain.agents import load_tools
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain.llms import WatsonxLLM
from langchain.memory import ConversationBufferMemory
from langchain.schema import SystemMessage, HumanMessage
from langchain.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain.chains import LLMChain, SequentialChain

from otel_lib.country_name import RandomCountryName
from opentelemetry.instrumentation.watsonx import WatsonxInstrumentor
from traceloop.sdk import Traceloop

load_dotenv(find_dotenv())

# Traceloop.init(api_endpoint=os.environ["OTLP_EXPORTER_GRPC"],
#                api_key=os.environ["TRACELOOP_API_KEY"],
#                app_name=os.environ["SVC_NAME"],
#                )

""" only need 2 lines code to instrument Langchain LLM
"""
from otel_lib.instrumentor import LangChainHandlerInstrumentor as SimplifiedLangChainHandlerInstrumentor
tracer_provider, metric_provider = SimplifiedLangChainHandlerInstrumentor().instrument(
    otlp_endpoint=os.environ["OTLP_EXPORTER_HTTP"],
    # otlp_endpoint=os.environ["OTLP_EXPORTER_GRPC"],
    metric_endpoint=os.environ["OTEL_METRICS_EXPORTER"],
    service_name=os.environ["SVC_NAME"],
    insecure = True,
    )
"""=======================================================
"""

os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")


# watson_ml_parameters = {
#     GenTextParamsMetaNames.DECODING_METHOD: "sample",
#     GenTextParamsMetaNames.MAX_NEW_TOKENS: 100,
#     GenTextParamsMetaNames.MIN_NEW_TOKENS: 1,
#     GenTextParamsMetaNames.TEMPERATURE: 0.5,
#     GenTextParamsMetaNames.TOP_K: 50,
#     GenTextParamsMetaNames.TOP_P: 1,
# }
            
# watson_ml_parameters = {
#     WatsonMLGenParams.DECODING_METHOD: "sample",
#     WatsonMLGenParams.MAX_NEW_TOKENS: 30,
#     WatsonMLGenParams.MIN_NEW_TOKENS: 1,
#     WatsonMLGenParams.TEMPERATURE: 0.5,
#     WatsonMLGenParams.TOP_K: 50,
#     WatsonMLGenParams.TOP_P: 1,
# }


# watsonx_ml_llm = WatsonxLLM(
#     # model_id="google/flan-ul2",
#     model_id="ibm/granite-13b-chat-v1",
#     url="https://us-south.ml.cloud.ibm.com",
#     project_id=os.getenv("PROJECT_ID"),
#     params=watson_ml_parameters,
# )

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
    # length_penalty={"decay_factor": 2.5, "start_index": 5},
    # repetition_penalty=1.2,
    truncate_input_tokens=2048,
    # random_seed=33,
    stop_sequences=["fail", "stop1"],
    return_options={
        "input_text": True, 
        "generated_tokens": True, 
        "input_tokens": True, 
        "token_logprobs": True, 
        "token_ranks": False, 
        "top_n_tokens": False
        },
)

watsonx_genai_llm = LangChainInterface(
    # model="google/flan-t5-xxl", 
    # model="meta-llama/llama-2-70b", 
    model = "ibm/granite-13b-chat-v1",
    params=genai_parameters, 
    credentials=creds
)


openai_llm = OpenAI(
    model="gpt-3.5-turbo-instruct",
    openai_api_key=os.environ["OPENAI_API_KEY"], 
    temperature=0.1
    )

# def langchain_serpapi_math_agent():
#     tools = load_tools(["serpapi", "llm-math"], llm=openai_llm)

#     agent = initialize_agent(
#         tools, watsonx_ml_llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=True)

#     print(agent.run("a pair of shoes sale price 300 CNY and a beautiful pocket knife price at 50 USD, how much in USD if I want them both?"))

# def langchain_chat_memory_agent():
    
#     memory = ConversationBufferMemory(memory_key="chat_history")
    
#     tools = load_tools(["serpapi", "llm-math"], llm=openai_llm)

#     agent = initialize_agent(tools, watsonx_ml_llm, agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION, verbose=True, memory=memory)
#     print(agent.run(f"what is the capital city of Italy?"))
#     print(agent.run("what is the most famous dish of this city?"))
#     print(agent.run("pls provide a receipe for this dish"))


def langchain_watson_genai_llm_chain():
    
    first_prompt_messages = [
        SystemMessage(content="answer the question with very short answer."),
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
    

langchain_watson_genai_llm_chain()
