from dotenv import load_dotenv
load_dotenv()

from langchain.schema.messages import HumanMessage, SystemMessage
from langchain.chat_models import ChatOpenAI

from llmonitor import agent

chat = ChatOpenAI()

@agent()
def TranslatorAgent(query):
  messages = [
    SystemMessage(content="You're a helpful assistant"),
    HumanMessage(content="What is the purpose of model regularization?"),
  ]

  res = chat.invoke(messages)

  return res

res = TranslatorAgent("Good morning")
print(res)