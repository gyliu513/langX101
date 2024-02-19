from dotenv import load_dotenv
load_dotenv()

from langsmith import Client

client = Client()
run = client.read_run("d24b423e-6931-45ec-a5c4-240bdb3beedf")
print(run.url)