"""Service for generating negative keyword phrases using OpenRouter."""
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List

import aiohttp
from dotenv import load_dotenv

from models import ProductDetails


load_dotenv()

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.environ.get("NEGATIVE_PHRASE_MODEL", "anthropic/claude-sonnet-4")
REQUEST_TIMEOUT = int(os.environ.get("REQUEST_TIMEOUT", 120))
PROMPT_PLACEHOLDER = "[Insert your product title, category, key features, target audience here]"
PROMPT_PATH = Path(__file__).resolve().with_name("negative_phrase_prompt.txt")


@lru_cache(maxsize=1)
def load_negative_prompt() -> str:
    """Load the negative phrase prompt template from disk."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_product_insert(product_details: ProductDetails) -> str:
    """Create the product summary block injected into the negative prompt."""
    parts = [
        f"ASIN: {product_details.asin or 'N/A'}",
        f"Brand: {product_details.brand or 'N/A'}",
        f"Product Title: {product_details.product_title or 'N/A'}",
        f"Description: {product_details.description or 'N/A'}",
        f"Product Features: {product_details.product_features or 'N/A'}",
    ]
    return "\n".join(parts)


def build_negative_prompt(product_details: ProductDetails) -> str:
    """Inject product information into the prompt template."""
    template = load_negative_prompt()
    product_block = build_product_insert(product_details)
    if PROMPT_PLACEHOLDER not in template:
        raise ValueError("Prompt placeholder not found in template")
    return template.replace(PROMPT_PLACEHOLDER, product_block)


async def generate_negative_phrases(product_details: ProductDetails) -> List[str]:
    """Call OpenRouter to generate negative keyword phrases for the product."""
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY not configured")

    prompt = build_negative_prompt(product_details)

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Keyword Analysis API",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.2,
        "max_tokens": 3000,
    }

    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with aiohttp.ClientSession() as session:
        async with session.post(OPENROUTER_API_URL, json=payload, headers=headers, timeout=timeout) as response:
            if response.status != 200:
                error_body = await response.text()
                raise RuntimeError(
                    f"OpenRouter request failed with status {response.status}: {error_body[:200]}"
                )

            result = await response.json()
            content = result["choices"][0]["message"]["content"].strip()

    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON array from model response: {exc}") from exc

    if not isinstance(parsed, list):
        raise ValueError("Model response was not a JSON array")

    phrases: List[str] = []
    for item in parsed:
        if isinstance(item, str):
            phrases.append(item)
        else:
            raise ValueError("Model response contained non-string items")

    return phrases
