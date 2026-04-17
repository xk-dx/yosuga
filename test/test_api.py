import os
from openai import OpenAI

api_key = os.getenv("OPENAI_API_KEY", "").strip()
api_base = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1").strip()
model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

print(f"API Base: {api_base}")
print(f"Model: {model}")

client = OpenAI(api_key=api_key, base_url=api_base)

try:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Say exactly: pong"}],
        max_tokens=500
    )
    print(f"Full response object: {response}")
    print(f"Choices: {response.choices}")
    if response.choices:
        print(f"Message: {response.choices[0].message}")
        print(f"Content: '{response.choices[0].message.content}'")
except Exception as e:
    print(f"Error: {e}")