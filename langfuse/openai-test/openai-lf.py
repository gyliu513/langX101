from dotenv import load_dotenv
import os
load_dotenv()

from langfuse.openai import openai

completion = openai.ChatCompletion.create(
  name="test-chat-openai",
  model="gpt-3.5-turbo",
  messages=[
      {"role": "system", "content": "You are a very accurate calculator. You output only the result of the calculation."},
      {"role": "user", "content": "1 + 1 = "}],
  temperature=0,
  metadata={"someMetadataKey": "someValue"},
)