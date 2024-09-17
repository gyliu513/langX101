# Use the native inference API to send a text message to Anthropic Claude.
from dotenv import load_dotenv
load_dotenv()

import boto3
import json

from botocore.exceptions import ClientError

# Create a Bedrock Runtime client in the AWS Region of your choice.
client = boto3.client("bedrock-runtime", region_name="us-east-1")

# Set the model ID, e.g., Claude 3 Haiku.
model_id = "anthropic.claude-v2"

# Define the prompt for the model.
# prompt = "Describe the purpose of a 'hello world' program in one line."

# Prepare the messages
'''
messages = [
    {
        "role": "system",
        "content": [{"type": "text", "text": "You are a helpful assistant that provides information about AWS services."}],
    },
    {
        "role": "user",
        "content": [{"type": "text", "text": "Tell me about AWS Bedrock"}],
    }
]

native_request = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 512,
    "temperature": 0.5,
    "messages": messages,
}
'''

# Format the request payload using the model's native structure.
native_request = {
    "system": "You are a helpful assistant that provides information about AWS services.",
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 512,
    "temperature": 0.5,
    "messages": [
        {
            "role": "user",
            "content": [{"type": "text", "text": "Tell me about AWS Bedrock"}],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Bedrock is an AI Platform"}],
        },
        
    ],
}


# Convert the native request to JSON.
request = json.dumps(native_request)

try:
    # Invoke the model with the request.
    response = client.invoke_model(modelId=model_id, body=request)

except (ClientError, Exception) as e:
    print(f"ERROR: Can't invoke '{model_id}'. Reason: {e}")
    exit(1)

# Decode the response body.
model_response = json.loads(response["body"].read())

# Extract and print the response text.
response_text = model_response["content"][0]["text"]
print(response_text)
