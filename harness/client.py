import os
from openai import OpenAI

_client = OpenAI(
    base_url=os.environ.get("GEMMA_ENDPOINT", "http://localhost:8889/v1"),
    api_key="sk-ignored",
)


def chat(messages, tools=None, **kwargs):
    return _client.chat.completions.create(
        model="gemma", messages=messages, tools=tools, **kwargs,
    )
