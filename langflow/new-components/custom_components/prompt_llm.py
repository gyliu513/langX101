from langflow import CustomComponent
from langchain.chains import LLMChain
from langchain import PromptTemplate
import requests

from langchain.llms.base import BaseLLM

from typing import Any, Callable, List, Mapping, Optional

from langchain.callbacks.manager import CallbackManagerForLLMRun
from langchain.llms.base import LLM
from langchain.llms.utils import enforce_stop_tokens
from langchain.pydantic_v1 import Field




class PromptLLM(CustomComponent):
    display_name = "PromptLLM"
    description = "This component leverage huggingface space service to generator a prompt"

    def build_config(self) -> dict:
        return { "Space URL": { "multiline": True, "required": True } }

    def build(self, url: str) -> BaseLLM:
        def _display_prompt(prompt: str) -> None:
            """Displays the given prompt to the user."""
            print(f"\n{prompt}")


        def _collect_user_input(
            separator: Optional[str] = None, stop: Optional[List[str]] = None
        ) -> str:
            """Collects and returns user input as a single string."""
            separator = separator or "\n"
            lines = []

            while True:
                line = input()
                if not line:
                    break
                lines.append(line)

                if stop and any(seq in line for seq in stop):
                    break
            # Combine all lines into a single string
            multi_line_input = separator.join(lines)
            return multi_line_input


        class SpaceLLM(LLM):
            """
            It returns user input as the response.
            """

            input_func: Callable = Field(default_factory=lambda: _collect_user_input)
            prompt_func: Callable[[str], None] = Field(default_factory=lambda: _display_prompt)
            separator: str = "\n"
            input_kwargs: Mapping[str, Any] = {}
            prompt_kwargs: Mapping[str, Any] = {}
            url: str = "https://merve-chatgpt-prompt-generator.hf.space/run/predict"

            @property
            def _identifying_params(self) -> Mapping[str, Any]:
                """
                Returns an empty dictionary as there are no identifying parameters.
                """
                return {}

            @property
            def _llm_type(self) -> str:
                """Returns the type of LLM."""
                return "human-input"

            def _call(
                self,
                prompt: str,
                stop: Optional[List[str]] = None,
                run_manager: Optional[CallbackManagerForLLMRun] = None,
                **kwargs: Any,
            ) -> str:
                """
                Displays the prompt to the user and returns their input as a response.

                Args:
                    prompt (str): The prompt to be displayed to the user.
                    stop (Optional[List[str]]): A list of stop strings.
                    run_manager (Optional[CallbackManagerForLLMRun]): Currently not used.

                Returns:
                    str: The user's input as a response.
                """
                self.prompt_func(prompt, **self.prompt_kwargs)

                output = ""
                TIMEOUT = 60
                # url = "https://merve-chatgpt-prompt-generator.hf.space/run/predict"

                response = requests.post(
                    self.url,
                    json={"data": [prompt]},
                    timeout=TIMEOUT,
                )
                try:
                    output = response.json()
                    print(output)
                except requests.JSONDecodeError as e:
                    raise RuntimeError(
                        f"Error decoding JSON from {url}. Text response: {response.text}"
                    ) from e
                return output["data"][0]

        return SpaceLLM(url=url)
