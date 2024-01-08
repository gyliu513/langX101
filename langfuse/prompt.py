from dotenv import load_dotenv
import os

load_dotenv()

import langfuse

# get current production version
prompt = langfuse.get_prompt("calculator")
 
# get specific version
# prompt = langfuse.get_prompt("prompt name", version=3)
 
# insert variables into prompt template
compiled_prompt = prompt.compile(input="test")