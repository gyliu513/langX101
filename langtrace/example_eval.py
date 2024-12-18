from inspect_ai import Task, task
from inspect_ai.dataset import csv_dataset
from inspect_ai.scorer import model_graded_fact
from inspect_ai.solver import self_critique, generate

@task
def example_eval():
    try:
        dataset = csv_dataset("langtracefs://cm4lrz7tq00075jmgkdtlq6w4")
        plan = [
            generate(),
            self_critique(model="openai/gpt-4o")
        ]
        scorer = model_graded_fact()
        
        return Task(
            dataset=dataset,
            plan=plan,
            scorer=scorer
        )
    except Exception as e:
        print(f"An error occurred: {e}")
        return None


# https://github.com/Scale3-Labs/langtrace-python-sdk/issues/434

'''
export INSPECT_LOG_FORMAT=json
export OPENAI_API_KEY="sk-..."
'''

'''
inspect eval example_eval.py --model openai/gpt-3.5-turbo --log-dir langtracefs://cm4lrz7tq00075jmgkdtlq6w4
inspect eval example_eval.py --model openai/gpt-4o-mini --log-dir langtracefs://cm4lrz7tq00075jmgkdtlq6w4
inspect eval example_eval.py --model anthropic/claude-3-5-sonnet-20240620 --log-dir langtracefs://cm4lrz7tq00075jmgkdtlq6w4
inspect eval example_eval.py --model ollama/llama3.1 --log-dir langtracefs://cm4lrz7tq00075jmgkdtlq6w4
'''
