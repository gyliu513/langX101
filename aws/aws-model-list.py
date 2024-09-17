from dotenv import load_dotenv
load_dotenv()

import boto3

# Initialize the Bedrock client (note the service_name is 'bedrock', not 'bedrock-runtime')
client = boto3.client(service_name="bedrock", region_name="us-west-2")

# List available foundation models
response = client.list_foundation_models()

# Print model IDs and their details
for model in response['modelSummaries']:
    print(f"Model ID: {model['modelId']}")
    print(f"Provider: {model.get('providerName', 'N/A')}")
    print("-" * 50)
