from datetime import datetime
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import openai_lib as openai

from uuid import uuid4
trace_id = str(uuid4())

now = datetime.now()
timestamp_str = now.strftime("%Y-%m-%d-%H:%M:%S")
        
completion = openai.ChatCompletion.create(
  name="test-chat-local-" + timestamp_str,
  metadata={"openai_chatCompletion": "testdata"},
  trace_id=trace_id,
  model="gpt-3.5-turbo",
  messages=[
      {"role": "system", "content": "You are a very accurate calculator. You output only the result of the calculation."},
      {"role": "user", "content": "1 + 1 = "}],
  temperature=0
)

print(completion)