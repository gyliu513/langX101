from dotenv import load_dotenv
load_dotenv()

import openai

from uuid import uuid4
from langsmith import traceable
from langsmith.run_trees import RunTree
from langsmith.wrappers import wrap_openai

messages = [
    { "role": "system", "content": "You are a helpful assistant. Please respond to the user's request only based on the given context." },
    { "role": "user", "content": "Is sunshine good for you?" }
]

# Collect run ID using RunTree
run_id = uuid4()
rt = RunTree(
    name="OpenAI Call RunTree",
    run_type="llm",
    inputs={"messages": messages},
    id=run_id
)
client = openai.Client()
chat_completion = client.chat.completions.create(
    model="gpt-3.5-turbo", messages=messages
)
rt.end(outputs=chat_completion)
rt.post()
print("RunTree Run ID: ", run_id)

# Collect run ID using openai_wrapper
run_id = uuid4()
client = wrap_openai(openai.Client())
completion = client.chat.completions.create(
    model="gpt-3.5-turbo", messages=messages, langsmith_extra={
        "run_id": run_id,
    },
)
print("OpenAI Wrapper Run ID: ", run_id)

# Collect run id using traceable decorator
run_id = uuid4()
@traceable(
    run_type="llm",
    name="OpenAI Call Decorator",
)
def call_openai(
    messages: list[dict], model: str = "gpt-3.5-turbo"
) -> str:
    return client.chat.completions.create(
        model=model,
        messages=messages,
    ).choices[0].message.content
result = call_openai(
    messages,
    langsmith_extra={
        "run_id": run_id,
    },
)
print("Traceable Run ID: ", run_id)