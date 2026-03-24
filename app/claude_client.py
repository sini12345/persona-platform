"""
Claude API client with streaming, prefill, and <indre>-tag parsing.

Key features:
- Streams responses via Server-Sent Events (SSE)
- Uses assistant prefill to force inner monologue (<indre> tags)
- Parses out <indre> content before sending to frontend
- Returns both full content (for DB) and visible content (for display)
"""
import re
import anthropic
from pathlib import Path
from typing import AsyncGenerator
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS, BASE_DIR


def get_client() -> anthropic.AsyncAnthropic:
    """Create an async Anthropic client."""
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def build_messages(conversation_history: list[dict], prefill: bool = True) -> list[dict]:
    """
    Build the messages array for the Claude API call.

    Args:
        conversation_history: List of {"role": "user"/"assistant", "content": "..."}
        prefill: Whether to add assistant prefill for inner monologue

    Returns:
        Messages array ready for the API
    """
    messages = []

    for msg in conversation_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Add assistant prefill to force inner monologue
    if prefill:
        messages.append({"role": "assistant", "content": "<indre>"})

    return messages


def strip_indre_tags(text: str) -> str:
    """Remove <indre>...</indre> tags and their content from text."""
    return re.sub(r"<indre>.*?</indre>\s*", "", text, flags=re.DOTALL).strip()


async def stream_response(
    system_prompt: str,
    conversation_history: list[dict],
) -> AsyncGenerator[dict, None]:
    """
    Stream a response from Claude, parsing <indre> tags in real-time.

    Yields dicts with:
        {"type": "indre", "text": "..."} — inner monologue chunk (hidden)
        {"type": "visible", "text": "..."} — visible response chunk (shown to student)
        {"type": "done", "full_content": "...", "visible_content": "..."} — final

    The streaming logic:
    1. Response starts with "<indre>" (from prefill)
    2. Claude writes inner monologue, then "</indre>"
    3. Everything after </indre> is visible to the student
    """
    client = get_client()
    messages = build_messages(conversation_history, prefill=True)

    full_content = "<indre>"  # Start with the prefill
    in_indre = True  # We start inside <indre> because of prefill
    visible_content = ""
    indre_content = ""
    buffer = ""  # Buffer for detecting </indre> tag

    try:
        async with client.messages.stream(
            model=CLAUDE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                full_content += text

                if in_indre:
                    buffer += text
                    close_pos = buffer.find("</indre>")

                    if close_pos != -1:
                        indre_text = buffer[:close_pos]
                        after_close = buffer[close_pos + len("</indre>"):]
                        indre_content += indre_text

                        yield {"type": "indre", "text": indre_content}

                        in_indre = False
                        buffer = ""

                        if after_close.strip():
                            visible_content += after_close
                            yield {"type": "visible", "text": after_close}
                    else:
                        if len(buffer) > 100:
                            indre_content += buffer
                            yield {"type": "indre", "text": buffer}
                            buffer = ""
                else:
                    visible_content += text
                    yield {"type": "visible", "text": text}

        # If we never left indre mode (shouldn't happen but safety)
        if in_indre and buffer:
            indre_content += buffer
            yield {"type": "indre", "text": buffer}

        # Final event with complete content
        yield {
            "type": "done",
            "full_content": full_content,
            "visible_content": visible_content.strip(),
        }

    except anthropic.AuthenticationError:
        yield {"type": "error", "text": "Ugyldig API-nøgle. Kontakt administrator."}
    except anthropic.RateLimitError:
        yield {"type": "error", "text": "API rate limit nået. Vent venligst og prøv igen."}
    except anthropic.APIError as e:
        yield {"type": "error", "text": f"API-fejl: {e.message}"}
    except Exception as e:
        yield {"type": "error", "text": f"Uventet fejl: {str(e)}"}


async def generate_evaluation(
    persona_name: str,
    scenario_name: str,
    mission_text: str,
    messages: list[dict],
) -> str:
    """
    Generate a post-conversation evaluation using Claude.

    Args:
        persona_name: Display name of the persona
        scenario_name: Scenario title
        mission_text: Mission description or "Åben dialog"
        messages: Full conversation history (including <indre> tags)

    Returns:
        Evaluation text as markdown
    """
    # Load evaluation prompt template
    template_path = BASE_DIR / "evaluering_prompt.md"
    template = template_path.read_text(encoding="utf-8")

    # Extract just the system prompt part (before ### Samtaledata)
    parts = template.split("### Samtaledata")
    system_part = parts[0].replace("## System prompt til evalueringskaldet\n\n", "").strip()

    # Build conversation log
    samtale_lines = []
    for msg in messages:
        role_label = "Studerende" if msg["role"] == "user" else persona_name
        samtale_lines.append(f"**{role_label}:** {msg['content']}")
    samtale_log = "\n\n".join(samtale_lines)

    # Build the full prompt with data section
    full_prompt = f"""{system_part}

### Samtaledata

**Persona:** {persona_name}
**Scenario:** {scenario_name}
**Mission:** {mission_text}
**Samtale:**
{samtale_log}"""

    client = get_client()
    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": full_prompt}],
    )

    return response.content[0].text


def sync_response(system_prompt: str, conversation_history: list[dict]) -> dict:
    """
    Non-streaming response for testing. Returns full and visible content.
    """
    client = get_client()
    messages = build_messages(conversation_history, prefill=True)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )

    full_content = "<indre>" + response.content[0].text
    visible_content = strip_indre_tags(full_content)

    return {
        "full_content": full_content,
        "visible_content": visible_content,
    }
