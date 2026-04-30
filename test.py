import os
import time
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["YUNWU_API_KEY"],
    base_url="https://yunwu.ai/v1",
)

models = [

    "deepseek-v4-pro",
]

prompt = "Return only one SQL query: count all rows from table singer."

for model in models:
    print("=" * 80)
    print("Testing:", model)

    start = time.time()

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0,
        )

        latency_ms = (time.time() - start) * 1000
        content = resp.choices[0].message.content

        print("STATUS: OK")
        print(f"LATENCY: {latency_ms:.1f} ms")
        print("OUTPUT:")
        print(content)

    except Exception as e:
        latency_ms = (time.time() - start) * 1000

        print("STATUS: FAILED")
        print(f"LATENCY BEFORE ERROR: {latency_ms:.1f} ms")
        print("ERROR:")
        print(e)