# This code is Apache 2 licensed:
# https://www.apache.org/licenses/LICENSE-2.0

from dotenv import load_dotenv
load_dotenv()

import boto3
import json

import re
import httpx

class ChatBot:
    def __init__(self, system=""):
        self.client = boto3.client(service_name="bedrock-runtime", region_name="us-west-2")
        self.system = system
        self.messages = ""
        if self.system:
            # self.messages.append({"role": "system", "content": system})
            self.messages = f"system: {system}\n"

    def __call__(self, message):
        self.messages = f"{self.messages}user: {message}\n"
        print("before call >>>>>>", self.messages)
        result = self.execute()
        self.messages = f"{self.messages}assistant: {result}\n"
        print("after call >>>>>>", self.messages)

        return result
    
    def execute(self):
        body = json.dumps({
            "inputText": self.messages, 
            "textGenerationConfig":{  
                "maxTokenCount":70,
                "stopSequences":[], #define phrases that signal the model to conclude text generation.
                "temperature":0, #Temperature controls randomness; higher values increase diversity, lower values boost predictability.
                "topP":0.9 # Top P is a text generation technique, sampling from the most probable tokens in a distribution.
            }
        })

        response = self.client.invoke_model(
            body=body,
            modelId="amazon.titan-text-express-v1",
            accept="application/json", 
            contentType="application/json"
        )

        response_body = json.loads(response.get('body').read())
        outputText = response_body.get('results')[0].get('outputText')
        return outputText

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
