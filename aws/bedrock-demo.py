# This code is Apache 2 licensed:
# https://www.apache.org/licenses/LICENSE-2.0

#from dotenv import load_dotenv
#load_dotenv()

import os
import boto3
import json
import logging

from botocore.exceptions import ClientError

import re
import httpx
import requests

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

Traceloop.init(app_name="chat_bot_service")

logger = logging.getLogger(__name__)

class ChatBot:
    def __init__(self, system=""):
        self.client = boto3.client(service_name="bedrock-runtime", region_name="us-east-1")
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

        model_id = "anthropic.claude-v2"


        try:
            # Invoke the model with the request.
            response = self.client.invoke_model(modelId=model_id, body=request)

        except (ClientError, Exception) as e:
            logger.debug(f"ERROR: Can't invoke '{model_id}'. Reason: {e}")
            return None

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
e.g. wikipedia: Hebei
Returns a summary from searching Wikipedia

google:
e.g. google: China
Returns the information of China from searching google

news:
e.g. news: China
Returns the latest of news about the China from NEWSDATA.IO. Use it when trying to get the realtime information!

Always look things up on google if you have the opportunity to do so.

Example session 1:

Question: What is the capital of Hebei?
Thought: I should look up Hebei on Wikipedia
Action: wikipedia: Hebei
PAUSE

You will be called again with this:

Observation: Hebei is a province in China. The capital is Shijiazhuang.

You then output:

Answer: The capital of Hebei is Shijiazhuang

Example session 2:

Question: What is the capital of China?
Thought: I should look up China on Wikipedia
Action: wikipedia: China
PAUSE

You will be called again with this:

Observation: China, officially the People's Republic of China (PRC), is a country in East Asia. With a population exceeding 1.4 billion, it is the world's second-most

Thought: I didn't get the Capital of China from wikipedia, Let me try it with google
Action: google: China
PAUSE

You will be called again with this:

Observation: officially the People's Republic of China (PRC), is a country in East Asia. With a population exceeding 1.4 billion, it is the world's second-most ...

Thought: I still didn't get the Capital of China, it seems like I got a lot of extra information instead
Action: google: capital of China
PAUSE

You will be called again with this:

Observation: Beijing, previously romanized as Peking, is the capital of China. With more than 22 million residents, Beijing is the world's most populous national capital ...; The modern day capital of China is Beijing (literally "Northern Capital"), which first served as China's capital city in 1261, when the Mongol ruler Kublai ...; Beijing, city, province-level shi (municipality), and capital of the People's Republic of China. Few cities in the world have served for so long as the ...

Thought: Okay, I finally got the capital of China!

Answer: The capital of China is Beijing
""".strip()


action_re = re.compile('^Action: (\w+): (.*)$')

@workflow(name="bedrock_chat_query")
def query(question, max_turns=3):
    logger.info(f"Query Bedrock for question: {question} ...")
    i = 0
    bot = ChatBot(prompt)
    next_prompt = question
    while i < max_turns:
        i += 1
        result = bot(next_prompt)
        if result == None:
          print("return None !!!")
          return

        print(result)
        actions = [action_re.match(a) for a in result.split('\n') if action_re.match(a)]
        if actions:
            # There is an action to run
            action, action_input = actions[0].groups()
            if action not in known_actions:
                continue
                #raise Exception("Unknown action: {}: {}".format(action, action_input))
            logger.info(" -- running {} {}".format(action, action_input))
            observation = known_actions[action](action_input)
            # logger.info("Observation:", observation)
            next_prompt = "Observation: {}".format(observation)
        else:
            logger.info("query return")
            logger.info(result)
            return

    logger.info("The question has been answered!")


@task(name="chat_bot_wiki")
def wikipedia(q):
    logger.warning("call wikipedia https://en.wikipedia.org/w/api.php ...")
    return httpx.get("https://en.wikipedia.org/w/api.php", params={
        "action": "query",
        "list": "search",
        "srsearch": q,
        "format": "json"
    }).json()["query"]["search"][0]["snippet"]


@task(name="chat_bot_calculate")
def calculate(what):
    logger.warning(f"call calculate eval({what}) ...")
    return eval(what)

@task(name="chat_bot_google")
def google(query):
    headers = {
        'X-API-KEY': os.environ['SERPER_API_KEY'],
        'Content-Type': 'application/json',
    }
    payload = {
        'q': query,
        'num': 5  # Number of search results to return
    }
    response = requests.post("https://google.serper.dev/search", json=payload, headers=headers)
    if response.status_code == 200:
        # for idx, result in enumerate(results.get('organic', []), start=1):
        rets = []
        for idx, result in enumerate(response.json().get('organic', []), start=1):
            rets.append(result.get('snippet'))
        return "; ".join(rets)
    else:
        response.raise_for_status()

known_actions = {
    "wikipedia": wikipedia,
    "calculate": calculate,
    #"google": google,
}

try:
  query("What is the captical of France")
except Exception as error:
  logger.debug("Traceloop: exception - " + error)
