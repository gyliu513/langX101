from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
client = OpenAI()

completion = client.chat.completions.create(
  model="o1-preview-2024-09-12",
  messages=[
    {"role": "system", "content": "You are a poetic assistant, skilled in explaining complex programming concepts with creative flair."},
    {"role": "user", "content": "Compose a poem that explains the concept of recursion in programming."}
  ]
)

print(completion)