from dotenv import load_dotenv
load_dotenv()
import os
from crewai import Agent, Task, Crew, Process
from crewai_tools import SerperDevTool
from crewai.llm import LLM

# Must precede any llm module imports

from langtrace_python_sdk import langtrace # type: ignore
from langtrace_python_sdk.utils.with_root_span import with_langtrace_root_span

'''
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    
otlp_exporter = OTLPSpanExporter(
    # This should match your collector's OTLP gRPC endpoint
    endpoint=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"),
    insecure=True  # Set to False if using HTTPS
)

langtrace.init(custom_remote_exporter=otlp_exporter, service_name="watsonx_crew_langtrace")
'''

langtrace.init(api_key=os.getenv("LANGTRACE_API_KEY"))

search_tool = SerperDevTool()

# CrewAI LLM config uses LiteLLM
WATSONX_MODEL_ID = "watsonx/ibm/granite-13b-chat-v2"
llm= LLM(
    model=WATSONX_MODEL_ID,
    base_url=os.getenv("WATSONX_URL"),
    project_id=os.getenv("WATSONX_PROJECT_ID"),
    max_tokens=2000,
    temperature=0.7
)


# Define the Agents
researcher = Agent(
 role='Senior Research Analyst',
 goal='Uncover cutting-edge developments in AI and data science',
 backstory="You are a Senior Research Analyst at a leading tech think tank.",
 verbose=True,
 allow_delegation=False,
 llm=llm,
 tool=search_tool # Tool for online searching
)

writer = Agent(
 role='Tech Content Strategist',
 goal='Craft compelling content on tech advancements',
 backstory="You are a renowned Tech Content Strategist, known for your insightful and engaging articles on technology and innovation.",
 verbose=True,
 allow_delegation=False,
 llm=llm,
 tool=search_tool # Tool for online searching
)

# Define the Tasks
task1 = Task(
 description="Perform an in-depth analysis of the following topic: {topic}",
 expected_output="Comprehensive analysis report in bullet points",
 agent=researcher
)

task2 = Task(
 description="Using the insights from the researcher\'s report, develop an engaging blog post that highlights the most significant AI advancements",
 expected_output="A compelling 3 paragraphs blog post formatted as markdown about the latest AI advancements in 2024",
 agent=writer,

)

# Create the crew
crew = Crew(
 agents=[researcher, writer],
 tasks=[task1, task2],
 verbose=True,
 process=Process.sequential
 
)

@with_langtrace_root_span() 
def watsonx_crew_kickoff(topic):
    return crew.kickoff(inputs={"topic":topic})

result=watsonx_crew_kickoff("Neural Network")
print(result)