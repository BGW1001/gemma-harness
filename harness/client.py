import os
from openai import AsyncOpenAI

_client = AsyncOpenAI(
    base_url=os.environ.get("GEMMA_ENDPOINT", "http://localhost:8889/v1"),
    api_key="sk-ignored",
)

async def chat(messages, tools=None, timeout=None, **kwargs):
    return await _client.chat.completions.create(
        model="gemma",
        messages=messages,
        tools=tools,
        timeout=timeout,
        **kwargs,
    )
