# Must precede any llm module imports

from dotenv import load_dotenv
load_dotenv()

import os
from langtrace_python_sdk import langtrace

langtrace.init(api_key=os.getenv("LANGTRACE_API_KEY"))

from openai import OpenAI
client = OpenAI()

completion = client.chat.completions.create(
  model="gpt-3.5-turbo",
  messages=[
    {"role": "system", "content": "You are a poetic assistant, skilled in explaining complex programming concepts with creative flair."},
    {"role": "user", "content": "Compose a poem that explains the concept of recursion in programming."}
  ]
)

print(completion.choices[0].message)
