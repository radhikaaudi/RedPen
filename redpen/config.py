import os
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

BASE_URL = os.getenv("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1/")

# Each Nemotron model has one job. See README "Which model does what".
MODEL_VISION = os.getenv("MODEL_VISION", "nvidia/Nemotron-3.5-Super-VL")
MODEL_FAST = os.getenv("MODEL_FAST", "nvidia/Nemotron-3_5-Lightning")
MODEL_REASONING = os.getenv("MODEL_REASONING", "nvidia/Nemotron-3-Ultra-550b-a55b")

# USD per 1M tokens (input, output), from the Token Factory pricing page.
PRICES = {
    MODEL_VISION: (0.30, 0.90),
    MODEL_FAST: (0.06, 0.24),
    MODEL_REASONING: (1.00, 3.00),
}

# Abuse guard for the public demo: model-backed requests per client IP per hour.
MAX_REQUESTS_PER_HOUR = int(os.getenv("REDPEN_MAX_REQUESTS_PER_HOUR", "120"))
MAX_PAGES_PER_SHEET = int(os.getenv("REDPEN_MAX_PAGES_PER_SHEET", "6"))
MAX_UPLOAD_MB = int(os.getenv("REDPEN_MAX_UPLOAD_MB", "15"))


@lru_cache
def client() -> OpenAI:
    api_key = os.getenv("NEBIUS_API_KEY")
    if not api_key:
        raise RuntimeError("NEBIUS_API_KEY is not set. Copy .env.example to .env and add your key.")
    return OpenAI(base_url=BASE_URL, api_key=api_key, timeout=180, max_retries=2)
