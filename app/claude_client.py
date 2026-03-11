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
from typing import AsyncGenerator
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS


def get_client() -> anthropic.Anthropic:
    """Create an Anthropic client."""
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


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

    with client.messages.stream(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            full_content += text

            if in_indre:
                # We're inside <indre> — accumulate and look for closing tag
                buffer += text
                close_pos = buffer.find("</indre>")

                if close_pos != -1:
                    # Found the closing tag
                    indre_text = buffer[:close_pos]
                    after_close = buffer[close_pos + len("</indre>"):]
                    indre_content += indre_text

                    yield {"type": "indre", "text": indre_content}

                    # Switch to visible mode
                    in_indre = False
                    buffer = ""

                    # Anything after </indre> is visible
                    if after_close.strip():
                        visible_content += after_close
                        yield {"type": "visible", "text": after_close}
                else:
                    # Still accumulating inner monologue
                    # Only yield if buffer is getting long (to show progress)
                    if len(buffer) > 100:
                        indre_content += buffer
                        yield {"type": "indre", "text": buffer}
                        buffer = ""
            else:
                # We're in visible mode — stream directly to student
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
