from dotenv import load_dotenv
load_dotenv()

import boto3
import json

# Initialize the Bedrock client
client = boto3.client(service_name="bedrock-runtime", region_name="us-west-2")

# Prepare the messages
messages = [
    {
        "role": "system",
        "content": "You are a helpful assistant that provides weather forecasts."
    },
    {
        "role": "user",
        "content": "What's the weather like today in New York City?"
    }
]

# Prepare the payload
payload = {
    "messages": messages,
    "max_tokens_to_sample": 150
}

# Invoke the model
response = client.invoke_model(
    modelId='amazon.titan-text-express-v1',  # Replace with your actual model ID
    accept='application/json',
    contentType='application/json',
    body=json.dumps(payload)
)

# Parse the response
response_body = json.loads(response['body'].read())
print(response_body['completion'])
