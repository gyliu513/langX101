from dotenv import load_dotenv
load_dotenv()

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow

Traceloop.init(app_name="crew_agent_openai_1")

from crewai import Crew, Agent, Task

# Create an agent with code execution enabled
coding_agent = Agent(
    role="Python Data Analyst",
    goal="Analyze data and provide insights using Python",
    backstory="You are an experienced data analyst with strong Python skills.",
    allow_code_execution=True
)

# Create a task that requires code execution
data_analysis_task = Task(
    description="Analyze the given dataset and calculate the average age of participants. Ages: {ages}",
    agent=coding_agent,
    expected_output="The average age calculated from the dataset"
)

# Create a crew and add the task
analysis_crew = Crew(
    agents=[coding_agent],
    tasks=[data_analysis_task],
    verbose=True,
    memory=False,
    respect_context_window=True  # enable by default
)

datasets = [
  { "ages": [25, 30] }
]

@workflow(name="crew_ai_kickoff_openai")
def crew_kickoff():
    # Get your crew to work!
    return analysis_crew.kickoff_for_each(inputs=datasets)

# Execute the crew
result = crew_kickoff()
