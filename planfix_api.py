import requests
from data import *

def planfix_get(_url) -> requests.Response:
    full_url = f"{BASE_URL}{_url}"

    headers = {
      'Accept': 'application/json',
      "Authorization": f"Bearer {BEARER_TOKEN}"
    }
    return requests.request("GET", full_url, headers=headers, data={})

def planfix_post(_url, _payload) -> requests.Response:
    full_url = f"{BASE_URL}{_url}"

    headers = {
      'Accept': 'application/json',
      "Authorization": f"Bearer {BEARER_TOKEN}"
    }
    return requests.post(full_url, headers=headers, json=_payload)
