
from dotenv import load_dotenv
load_dotenv()

from litellm import completion

response = completion(
  model="bedrock/amazon.titan-text-express-v1",
  messages=[{ "content": "Tell me sth about IBM?","role": "user"}]
)

print(response)
