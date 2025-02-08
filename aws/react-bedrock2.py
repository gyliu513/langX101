# This code is Apache 2 licensed:
# https://www.apache.org/licenses/LICENSE-2.0

from dotenv import load_dotenv
load_dotenv()

import boto3
import json

from botocore.exceptions import ClientError

import re
import httpx

class ChatBot:
    def __init__(self, system=""):
        self.client = boto3.client(service_name="bedrock-runtime", region_name="us-west-2")
        self.system = system
        self.messages = []
    def __call__(self, message):
        self.messages.append({"role": "user", "content": message})
        result = self.execute()
        self.messages.append({"role": "assistant", "content": result})
        return result
    
    def execute(self):
        native_request = {
            "system": self.system,
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "temperature": 0.5,
            "messages": self.messages,
        }


        # Convert the native request to JSON.
        request = json.dumps(native_request)

        model_id = "anthropic.claude-v2:0"
        

        try:
            # Invoke the model with the request.
            response = self.client.invoke_model(modelId=model_id, body=request)

        except (ClientError, Exception) as e:
            print(f"ERROR: Can't invoke '{model_id}'. Reason: {e}")
            exit(1)

        # Decode the response body.
        model_response = json.loads(response["body"].read())

        # Extract and print the response text.
        response_text = model_response["content"][0]["text"]
        return response_text

prompt = """
You run in a loop of Thought, Action, PAUSE, Observation.
At the end of the loop you output an Answer
Use Thought to describe your thoughts about the question you have been asked.
Use Action to run one of the actions available to you - then return PAUSE.
Observation will be the result of running those actions.

Your available actions are:

calculate:
e.g. calculate: 4 * 7 / 3
Runs a calculation and returns the number - uses Python so be sure to use floating point syntax if necessary

wikipedia:
e.g. wikipedia: LLM
Returns a summary from searching Wikipedia

Example session:

Question: What is the capital of Hebei?
Thought: I should look up Hebei on Wikipedia
Action: wikipedia: Hebei
PAUSE

You will be called again with this:

Observation: Hebei is a province in China. The capital is Shijiazhuang.

You then output:

Answer: The capital of Hebei is Shijiazhuang
""".strip()


action_re = re.compile('^Action: (\w+): (.*)$')

def query(question, max_turns=3):
    i = 0
    bot = ChatBot(prompt)
    next_prompt = question
    while i < max_turns:
        i += 1
        result = bot(next_prompt)
        # print(result)
        actions = [action_re.match(a) for a in result.split('\n') if action_re.match(a)]
        if actions:
            # There is an action to run
            action, action_input = actions[0].groups()
            if action not in known_actions:
                raise Exception("Unknown action: {}: {}".format(action, action_input))
            print(" -- running {} {}".format(action, action_input))
            observation = known_actions[action](action_input)
            print("Observation:", observation)
            next_prompt = "Observation: {}".format(observation)
        else:
            print(result)
            return


def wikipedia(q):
    return httpx.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query",
        "list": "search",
        "srsearch": q,
        "format": "json"
    }).json()["query"]["search"][0]["snippet"]


def calculate(what):
    return eval(what)

known_actions = {
    "wikipedia": wikipedia,
    "calculate": calculate,
}

query("What is the captical of Hebei")
