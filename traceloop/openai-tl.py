from dotenv import load_dotenv
import os
load_dotenv()

from traceloop.sdk import Traceloop
  
Traceloop.init(disable_batch=True, api_key=os.getenv("TRACELOOP_API_KEY"))

from openai import OpenAI

client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key=os.getenv("OPENAI_API_KEY"),
)

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Say this is a test",
        }
    ],
    model="gpt-3.5-turbo",
)

print(chat_completion)
