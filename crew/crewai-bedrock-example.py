from crewai import Agent, Task, Crew, Process
from crewai.llm import LLM

from crewai_tools import SerperDevTool

from pydantic import BaseModel

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import workflow
Traceloop.init(app_name="bedrock_crew")

search_tool = SerperDevTool()

# CrewAI LLM config uses LiteLLM
llm=LLM(
        model="bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0"
    )

class JsonOutput(BaseModel):
    agent: str
    expected_output: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    successful_requests: int


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
 output_json=JsonOutput
)

# Create the crew
crew = Crew(
 agents=[researcher, writer],
 tasks=[task1, task2],
 verbose=True,
 process=Process.sequential
 
)


@workflow(name="bedrock_kickoff")
def bedrock_crew_kickoff(topic):
    return crew.kickoff(inputs={"topic":topic})

result=bedrock_crew_kickoff("Artificial Intelligence")
print(result)
