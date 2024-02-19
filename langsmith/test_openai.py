from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from langsmith import wrappers

client = wrappers.wrap_openai(OpenAI())

client.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Say this is a test"}],
)