from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant. Please respond to the user's request only based on the given context."),
    ("user", "Question: {question}\nContext: {context}")
])
model = ChatOpenAI(model="gpt-3.5-turbo")
output_parser = StrOutputParser()

chain = prompt | model | output_parser

question = "Can you summarize this morning's meetings?"
context = "During this morning's meeting, we solved all world conflict."
chain.invoke({"question": question, "context": context})

# # You can set the project name for a specific tracer instance:
# from langchain.callbacks.tracers import LangChainTracer

# tracer = LangChainTracer(project_name="evaluators")
# chain.invoke({"query": "How many people live in canada as of 2023?"}, config={"callbacks": [tracer]})


# # LangChain python also supports a context manager for tracing a specific block of code.
# # You can set the project name using the project_name parameter.
# from langchain_core.tracers.context import tracing_v2_enabled
# with tracing_v2_enabled(project_name="evaluators"):
#     chain.invoke({"query": "How many people live in canada as of 2023?"})