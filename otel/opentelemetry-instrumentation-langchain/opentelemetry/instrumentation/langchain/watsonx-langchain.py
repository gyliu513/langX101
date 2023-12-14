"""Langchain BaseHandler instrumentation"""
import logging
from typing import Collection

from opentelemetry.trace import get_tracer
from opentelemetry.instrumentation.langchain.version import __version__
from opentelemetry.semconv.ai import TraceloopSpanKindValues
from otel_lib.instrumentor import LangChainHandlerInstrumentor


logger = logging.getLogger(__name__)

_instruments = ("langchain >= 0.0.200",)


from dotenv import load_dotenv, find_dotenv
import os
load_dotenv(find_dotenv())

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'

import sys

from opentelemetry import trace
# from opentelemetry.instrumentation.wsgi import collect_request_attributes
from opentelemetry.propagate import extract
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter


from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
)
from opentelemetry.trace import (
    SpanKind,
    get_tracer_provider,
    set_tracer_provider,
)

tracer_provider = TracerProvider(
    resource=Resource.create({'service.name': os.environ["SVC_NAME"]}),
)

# Create an OTLP Span Exporter
otlp_exporter = OTLPSpanExporter(
    endpoint=os.environ["OTLP_EXPORTER"]+":4317",  # Replace with your OTLP endpoint URL
)

# Add the exporter to the TracerProvider
# tracer_provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))  # Add any span processors you need
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))

# Register the TracerProvider
trace.set_tracer_provider(tracer_provider)

LangChainHandlerInstrumentor().instrument(tracer_provider=tracer_provider)

from dotenv import load_dotenv
import os
load_dotenv()

os.environ['OTEL_EXPORTER_OTLP_INSECURE'] = 'True'
os.environ["WATSONX_APIKEY"] = os.getenv("IAM_API_KEY")

# from ibm_watson_machine_learning.metanames import GenTextParamsMetaNames as GenParams

# parameters = {
#     GenParams.DECODING_METHOD: "sample",
#     GenParams.MAX_NEW_TOKENS: 30,
#     GenParams.MIN_NEW_TOKENS: 1,
#     GenParams.TEMPERATURE: 0.5,
#     GenParams.TOP_K: 50,
#     GenParams.TOP_P: 1,
# }

# from langchain.llms import WatsonxLLM

# watsonx_llm = WatsonxLLM(
#     model_id="google/flan-ul2",
#     url="https://us-south.ml.cloud.ibm.com",
#     project_id=os.getenv("PROJECT_ID"),
#     params=parameters,
# )

from genai.extensions.langchain import LangChainInterface
from genai.schemas import GenerateParams as GenaiGenerateParams
from genai.credentials import Credentials

api_key = os.getenv("IBM_GENAI_KEY", None) 
api_url = "https://bam-api.res.ibm.com"
creds = Credentials(api_key, api_endpoint=api_url)

genai_parameters = GenaiGenerateParams(
    decoding_method="greedy",  # Literal['greedy', 'sample']
    max_new_tokens=50,
    min_new_tokens=10,
    top_p=1,
    top_k=50,
    temperature=0.1,
    time_limit=30000,
)

watsonx_genai_llm = LangChainInterface(
#     model="google/flan-t5-xxl", 
    model="meta-llama/llama-2-70b", 
    params=genai_parameters, 
    credentials=creds
)

from langchain.prompts import PromptTemplate
from langchain.agents import load_tools
from langchain.agents import initialize_agent
from langchain.agents import AgentType
from langchain.llms import OpenAI


def langchain_serpapi_math_agent():
    openai_llm = OpenAI(openai_api_key=os.environ["OPENAI_API_KEY"], temperature=0.1)

    tools = load_tools(["serpapi", "llm-math"], llm=watsonx_genai_llm)

    agent = initialize_agent(
        tools, openai_llm, agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION, verbose=True)

    # agent.run("My monthly salary is 10000 KES, if i work for 10 months. How much is my total salary in USD in those 10 months.")
    agent.run("a pair of shoes sale price 300 CNY and a beautiful pocket knife price at 50 USD, how much in USD if I want them both?")

def langchain_chat_memory_agent():
    from langchain.memory import ConversationBufferMemory
    
    memory = ConversationBufferMemory(memory_key="chat_history")
    
    tools = load_tools(["serpapi", "llm-math"], llm=watsonx_genai_llm)

    agent = initialize_agent(tools, watsonx_genai_llm, agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION, verbose=True, memory=memory)
    agent.run("what is the capital city of Italy?")
    agent.run("what is the most famous dish of this city?")
    agent.run("pls provide a receipe for this dish")



langchain_serpapi_math_agent()

# langchain_chat_memory_agent()