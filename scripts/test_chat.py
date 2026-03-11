import hmac
import hashlib
import time
import requests
import json
import os
from pathlib import Path

# Try to load from .env or os.environ
secret = os.environ.get("BACKEND_API_TOKEN", "test_secret_key")
env_path = Path(__file__).parent.parent / '.env'
if not os.environ.get("BACKEND_API_TOKEN") and env_path.exists():
    with open(env_path, 'r') as f:
        for line in f:
            if line.startswith("BACKEND_API_TOKEN="):
                secret = line.split("=")[1].strip()

def generate_signature(timestamp: str) -> str:
    message = timestamp.encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{timestamp}.{sig}"

def test_chat():
    url = "http://localhost:5000/api/chat/"
    payload = {
        "akte_id": 12,
        "messages": [
            {"role": "user", "content": "Welche offene posten gibt es da?"}
        ],
        "kontext": {}
    }
    body_str = json.dumps(payload, separators=(',', ':'))
    timestamp = str(int(time.time()))
    signature = generate_signature(timestamp)
    
    headers = {
        "Content-Type": "application/json",
        "X-KI-Timestamp": timestamp,
        "X-KI-Signature": signature
    }
    
    print(f"Sending request to {url}")
    print(f"Payload: {payload}")
    response = requests.post(url, data=body_str, headers=headers)
    
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    test_chat()
