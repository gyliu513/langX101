from dotenv import load_dotenv
load_dotenv()

import langsmith

from langchain import chat_models, smith

# Replace with the chat model you want to test
my_llm = chat_models.ChatOpenAI(temperature=0)

# Define the evaluators to apply
eval_config = smith.RunEvalConfig(
    evaluators=[
        "cot_qa"
    ],
    custom_evaluators=[],
    eval_llm=chat_models.ChatOpenAI(model="gpt-4", temperature=0)
)

client = langsmith.Client()
chain_results = client.run_on_dataset(
    dataset_name="ds-scholarly-sandbar-56",
    llm_or_chain_factory=my_llm,
    evaluation=eval_config,
    project_name="test-large-elimination-13",
    concurrency_level=5,
    verbose=True,
)