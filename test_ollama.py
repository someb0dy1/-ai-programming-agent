import os
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434/api/chat"
)

MODEL = os.getenv(
    "MODEL",
    "qwen2.5:7b"
)

payload = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "你好，请简单介绍一下你自己。"
        }
    ],
    "stream": False
}

response = requests.post(
    OLLAMA_URL,
    json=payload,
    timeout=120
)

response.raise_for_status()

data = response.json()

print("AI：")
print(data["message"]["content"])
