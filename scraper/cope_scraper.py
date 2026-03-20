import anthropic
import json
import re
from scraper.prompts import SYSTEM_PROMPT, user_prompt
from config import settings


async def search_cope(address: str, municipality: dict) -> dict:
    if not settings.anthropic_api_key:
        return {"error": "AI service not configured"}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=2000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": user_prompt(
                    address,
                    municipality["search_url"],
                    municipality["search_type"],
                ),
            }],
        )
    except anthropic.APITimeoutError:
        return {"error": "Search timed out. The property database may be unavailable."}
    except anthropic.APIError as e:
        return {"error": f"API error: {str(e)}"}

    # Extract final text block (after tool use)
    text_blocks = [b.text for b in response.content if hasattr(b, "text")]
    raw_text = "\n".join(text_blocks)

    # Strip markdown fences if present
    json_match = re.search(r'\{[\s\S]*\}', raw_text)
    if not json_match:
        return {"error": "Could not parse response from property database"}

    try:
        return json.loads(json_match.group())
    except json.JSONDecodeError:
        return {"error": "Malformed JSON in response"}
