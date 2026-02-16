import json, requests, os
from typing import Dict, Any


class Nemotron:
    def __init__(self, nim_url: str, api_key: str = None):
        self.api_endpoint = f"{nim_url}/v1/chat/completions"
        self.api_key = api_key
        self.model = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

    def orchestrate(self, system_prompt: str, user_prompt: str):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2
        }
        response = requests.post(self.api_endpoint, headers=headers, json=payload)
        content = response.json()['choices'][0]['message']['content']
        # Handle potential markdown code blocks in JSON response
        return content.replace('```json', '').replace('```', '').strip()
