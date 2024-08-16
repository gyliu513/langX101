'''
(titan) gyliu@Guangyas-MacBook-Air .aws % cat credentials
[bedrock-admin]
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

(titan) gyliu@Guangyas-MacBook-Air .aws % pwd
/Users/gyliu/.aws
'''

from dotenv import load_dotenv
load_dotenv()

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

Traceloop.init(app_name="joke_generation_service")

from langchain_aws import BedrockLLM

llm = BedrockLLM(
    credentials_profile_name="bedrock-admin",
    model_id="amazon.titan-text-express-v1",
    region_name="us-west-2",
)

print(llm.invoke(input="What is the recipe of mayonnaise?"))
