from dotenv import load_dotenv
load_dotenv()

import os

from traceloop.sdk import Traceloop
from traceloop.sdk.decorators import task, workflow
from pydantic import BaseModel

Traceloop.init(app_name="watsonx_crew_agent")

from crewai import Agent, Task, Crew, Process, LLM
from ibm_watsonx_ai.foundation_models import Model
from ibm_watsonx_ai.credentials import Credentials
from crewai_tools import ScrapeWebsiteTool
import os
from langchain_community.tools import DuckDuckGoSearchRun 

search_tool = DuckDuckGoSearchRun()
scrape_tool = ScrapeWebsiteTool()

model_id = "meta-llama/llama-3-70b-instruct"
parameters = {
    "decoding_method": "sample",
    "max_new_tokens": 1000,
    "temperature": 0.7,
    "top_k": 50,
    "top_p": 1,
    "repetition_penalty": 1
}

api_key = os.getenv("WATSONX_API_KEY")
project_id = os.getenv("WATSONX_PROJECT_ID")
url = os.getenv("WATSONX_URL")

credentials = Credentials(url=url, api_key=api_key)

ibm_model = Model(
    model_id=model_id,
    params=parameters,
    credentials=credentials,
    project_id=project_id
)

WATSONX_MODEL_ID = "watsonx/ibm/granite-13b-chat-v2"
    
custom_llm = LLM(
    model=WATSONX_MODEL_ID,
    base_url=os.getenv("WATSONX_URL"),
    project_id=os.getenv("WATSONX_PROJECT_ID"),
    max_tokens=2000,
    temperature=0.7
)

class JsonOutput(BaseModel):
    agent: str
    expected_output: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    successful_requests: int

# Agents
data_collector = Agent(
    role='Data Collector',
    goal='Collect accurate and up-to-date financial data',
    backstory='You are an expert in gathering financial data from various sources.',
    tools=[scrape_tool, search_tool],
    verbose=True,
    allow_delegation=True,
    llm=custom_llm
)

financial_analyst = Agent(
    role='Financial Analyst',
    goal='Analyze financial data and provide insights',
    backstory='You are a seasoned financial analyst with years of experience in interpreting market trends.',
    verbose=True,
    allow_delegation=True,
    tools=[scrape_tool, search_tool],
    llm=custom_llm
)

report_writer = Agent(
    role='Report Writer',
    goal='Compile findings into a comprehensive report',
    backstory='You are skilled at creating clear and concise financial reports.',
    llm=custom_llm
)

# Task
data_collector_task = Task(
    description='Collect stock data for {company_name} from their company website {company_website} and yahoo finance site {yahoo_finance} for the past month',
    expected_output="A comprehensive dataset containing daily stock prices, trading volumes, and any significant news or events affecting these stocks over the past month.",
    agent=data_collector
)

financial_analyst_task = Task(
    description='Analyze the collected data and identify trends',
    expected_output="A detailed analysis report highlighting key trends, patterns, and insights derived from the collected stock data, including potential correlations and anomalies.",
    agent=financial_analyst,
    output_json=JsonOutput
)

report_writer_task = Task(
    description='Write a comprehensive report on the financial analysis',
    expected_output="A well-structured, easy-to-understand report summarizing the findings from the data collection and analysis, including actionable insights and recommendations for potential investors or stakeholders.",
    agent=report_writer,
    output_json=JsonOutput
)

# Create the crew
financial_crew = Crew(
    agents=[
        data_collector, 
        financial_analyst, 
        report_writer
    ],
    tasks=[
        data_collector_task, 
        financial_analyst_task, 
        report_writer_task
    ],
    process=Process.sequential
)

inputs = {
    'company_name': 'Tesla Inc.',
    'company_website': 'https://www.tesla.com/',
    'yahoo_finance': 'https://finance.yahoo.com/quote/TSLA'
}

@workflow(name="crew_ai_kickoff")
def financial_crew_kickoff():
    # Get your crew to work!
    return financial_crew.kickoff(inputs)

result = financial_crew_kickoff()
print(result)