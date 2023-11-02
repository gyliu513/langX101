
from dotenv import load_dotenv
load_dotenv()

from langfuse import Langfuse
 
langfuse = Langfuse()

from datetime import datetime
from langfuse.model import InitialGeneration, Usage


 
generationStartTime = datetime.now()
 
# call to an LLM API
 
generation = langfuse.generation(InitialGeneration(
    name="summary-generation",
    startTime=generationStartTime,
    endTime=datetime.now(),
    model="gpt-3.5-turboxxxxx",
    modelParameters={"maxTokens": "1000", "temperature": "0.9"},
    prompt=[{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": "Please generate a summary of the following documents \nThe engineering department defined the following OKR goals...\nThe marketing department defined the following OKR goals..."}],
    completion="The Q3 OKRs contain goals for multiple teams...",
    usage=Usage(promptTokens=50, completionTokens = 49),
    metadata={"interface": "whatsapp"}
))

langfuse.flush()