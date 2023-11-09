from dotenv import load_dotenv
import os
load_dotenv()
import openai

openai.api_key = os.getenv("OPENAI_API_KEY")

response = openai.Completion.create(
    engine="text-davinci-002",
    prompt="Generate some text...",
    max_tokens=50,
)
