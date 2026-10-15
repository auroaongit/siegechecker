"""Step 1: turn a photo of the screen into a list of usernames.

We send the photo to Claude (an AI that can read images) and ask it to
reply in a fixed JSON shape, so our code always knows what it gets back.
"""

import base64

from anthropic import AsyncAnthropic
from pydantic import BaseModel

# AsyncAnthropic reads ANTHROPIC_API_KEY from the environment (our .env file).
client = AsyncAnthropic()


class Teams(BaseModel):
    """The exact shape we want Claude's answer in."""

    enemy: list[str]
    allies: list[str]


PROMPT = """This is a phone photo of a Rainbow Six Siege screen (a scoreboard,
team lineup or loading screen). It may be at an angle, blurry or have glare.

List every player username you can see, split into the two teams.
- "allies" is the photographer's own team, shown in BLUE by default.
- "enemy" is the other team, shown in ORANGE by default.
- If the colours are unclear, the team listed first or on top is "allies".

Copy each name exactly, character for character: keep upper/lower case,
digits, underscores, dots and hyphens. Watch out for look-alikes such as
l / I / 1 and O / 0. Do not include clan tags, ranks or other text.
If you can't see any names, return empty lists."""


class NameReadError(Exception):
    pass


async def read_names(image_bytes: bytes, media_type: str) -> Teams:
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    response = await client.beta.messages.parse(
        model="claude-opus-5-5",
        max_tokens=4000,
        # Reading names is an easy job, so "low" effort keeps it fast and cheap.
        output_config={"effort": "low"},
        # If a request is ever declined, retry it on a backup model automatically.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_format=Teams,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_b64},
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise NameReadError("Couldn't read names from that photo. Try another one.")
    return response.parsed_output
