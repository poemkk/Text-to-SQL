import os
import time
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

model = "deepseek-v4-pro"
prompt = "Return only one SQL query: count all rows from table singer."

for i in range(5):
    print("=" * 60)
    print(f"Test {i + 1}/5")

    start = time.time()

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    latency_ms = (time.time() - start) * 1000

    print(f"Latency: {latency_ms:.1f} ms")
    print(resp.choices[0].message.content)
