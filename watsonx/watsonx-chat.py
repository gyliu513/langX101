import os
import time

from dotenv import load_dotenv

from genai.credentials import Credentials
from genai.model import Model
from genai.schemas import GenerateParams

# make sure you have a .env file under genai root with
# GENAI_KEY=<your-genai-key>
# GENAI_API=<genai-api-endpoint>
load_dotenv()
api_key = os.getenv("GENAI_KEY", None)
api_endpoint = os.getenv("GENAI_API", None)

print("\n------------- Example (Model QA)-------------\n")

bob_params = GenerateParams(
    decoding_method="sample",
    max_new_tokens=25,
    min_new_tokens=1,
    stream=False,
    temperature=1,
    top_k=50,
    top_p=1,
)

creds = Credentials(api_key, api_endpoint)
bob_model = Model("google/flan-ul2", params=bob_params, credentials=creds)

alice_q = "What is 1 + 1?"
print(f"[Alice][Q] {alice_q}")


aliceq = [alice_q]
bob_response = bob_model.generate(aliceq)
bob_a = bob_response[0].generated_text
print(f"[Bob][A] {bob_a}")
