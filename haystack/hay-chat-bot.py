from dotenv import load_dotenv
load_dotenv()

from haystack.telemetry import tutorial_running

tutorial_running(40)
'''
from haystack.dataclasses import ChatMessage
from haystack.components.generators.chat import OpenAIChatGenerator

messages = [
    ChatMessage.from_system("Always respond in German even if some input data is in other languages."),
    ChatMessage.from_user("What's Natural Language Processing? Be brief."),
]

chat_generator = OpenAIChatGenerator(model="gpt-3.5-turbo")
chat_generator.run(messages=messages)
'''
'''
from haystack.dataclasses import ChatMessage
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.components.generators.utils import print_streaming_chunk

messages = [
    ChatMessage.from_system("Always respond in German even if some input data is in other languages."),
    ChatMessage.from_user("What's Natural Language Processing? Be brief."),
]

chat_generator = OpenAIChatGenerator(model="gpt-3.5-turbo", streaming_callback=print_streaming_chunk)
response = chat_generator.run(messages=messages)
print(response)
'''