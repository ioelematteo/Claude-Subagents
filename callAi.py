import os

from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv('DEEPSEEK_API_KEY'),
    base_url=os.getenv('DEEPSEEK_BASE_URL')
)

async def call(
    msg: str,
    system: str = "You are a helpful assistant",
    model: str = "deepseek-flash",
    thinking: bool = True,
    effort: str | None = "high",
    with_usage: bool = False,
):

    options = {}
    if thinking:
        options["extra_body"] = {"thinking": {"type": "enabled"}}
        if effort:
            options["reasoning_effort"] = effort
    else:
        options["extra_body"] = {"thinking": {"type": "disabled"}}

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": msg},
        ],
        stream=False,
        **options
    )

    content = response.choices[0].message.content
    if with_usage:
        return content, response.usage
    return content
