from dotenv import load_dotenv
load_dotenv()

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

from opentelemetry.sdk.trace.export import ConsoleSpanExporter
from opentelemetry.sdk._logs.export import ConsoleLogExporter
Traceloop.init(app_name="crewai_bedrock_agent_1", exporter=ConsoleSpanExporter())

import os
from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import SerperDevTool

search_tool = SerperDevTool()

llm = LLM(
    # credentials_profile_name="bedrock-admin",
    # model_id="amazon.titan-text-express-v1",
    # model_id="amazon.titan-embed-text-v2:0",
    # model="bedrock/anthropic.claude-v2",
    model="bedrock/amazon.titan-text-express-v1",
)

# Define your agents with roles and goals
researcher = Agent(
  role='Senior Research Analyst',
  goal='Uncover cutting-edge developments in AI and data science',
  backstory="""You work at a leading tech think tank.
  Your expertise lies in identifying emerging trends.
  You have a knack for dissecting complex data and presenting actionable insights.""",
  verbose=True,
  llm=llm,
  allow_delegation=False,
  tools=[search_tool]
)
writer = Agent(
  role='Tech Content Strategist',
  goal='Craft compelling content on tech advancements',
  backstory="""You are a renowned Content Strategist, known for your insightful and engaging articles.
  You transform complex concepts into compelling narratives.""",
  verbose=True,
  llm=llm,
  allow_delegation=True
)

# Create tasks for your agents
task1 = Task(
  description="""Conduct a comprehensive analysis of the latest advancements in AI in 2024.
  Identify key trends, breakthrough technologies, and potential industry impacts.""",
  expected_output="Full analysis report in bullet points",
  agent=researcher
)

task2 = Task(
  description="""Using the insights provided, develop an engaging blog
  post that highlights the most significant AI advancements.
  Your post should be informative yet accessible, catering to a tech-savvy audience.
  Make it sound cool, avoid complex words so it doesn't sound like AI.""",
  expected_output="Full blog post of at least 4 paragraphs",
  agent=writer
)

# Instantiate your crew with a sequential process
crew = Crew(
  agents=[researcher],
  tasks=[task1],
  verbose=True,
  process = Process.sequential
)

'''
# Instantiate your crew with a sequential process
crew = Crew(
  agents=[researcher, writer],
  tasks=[task1, task2],
  verbose=True,
  process = Process.sequential
)
'''

@workflow(name="crew_ai_kickoff")
def crew_kickoff():
    # Get your crew to work!
    return crew.kickoff()

print("######################")
result = crew_kickoff()
print(result)
