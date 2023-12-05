from dotenv import load_dotenv
import os
load_dotenv()

from openai import OpenAI

from nr_openai_observability import monitor

monitor.initialization(application_name="gyliu-openai", license_key=os.getenv("NEW_RELIC_LICENSE_KEY"))

client = OpenAI(
    # defaults to os.environ.get("OPENAI_API_KEY")
    api_key=os.getenv("OPENAI_API_KEY"),
)

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Say this is a test",
        }
    ],
    model="gpt-3.5-turbo",
)

print(chat_completion)