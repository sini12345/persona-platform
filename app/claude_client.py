"""
Claude API client with streaming, prefill, and <indre>-tag parsing.

Key features:
- Streams responses via Server-Sent Events (SSE)
- Relies on the system prompt to open every reply with an <indre> tag
- Parses out <indre> content before sending to frontend
- Returns both full content (for DB) and visible content (for display)
"""
import logging
import re
import anthropic
from typing import AsyncGenerator
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS

logger = logging.getLogger(__name__)


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
    """Remove <indre>...</indre> tags and their content from text.

    An <indre> that is never closed (e.g. the reply was cut off) is removed
    through the end of the text, so the monologue can't leak.
    """
    return re.sub(r"<indre>.*?(?:</indre>\s*|$)", "", text, flags=re.DOTALL).strip()


def extract_text(response) -> str:
    """Concatenate all text blocks from a Claude message response.

    Safer than response.content[0].text, which assumes the first block is
    text — that is not guaranteed for every response shape.
    """
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )


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
    1. Response opens with "<indre>" (the system prompt mandates it)
    2. Claude writes inner monologue, then "</indre>"
    3. Everything after </indre> is visible to the student
    """
    client = get_client()
    messages = build_messages(conversation_history, prefill=False)

    full_content = ""
    in_indre = True  # The system prompt instructs the model to open with <indre>
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

            final = await stream.get_final_message()

        if final.stop_reason == "refusal":
            category = getattr(getattr(final, "stop_details", None), "category", None)
            logger.warning("Refusal from %s (category=%s)", CLAUDE_MODEL, category)
            yield {"type": "error", "text": "Personaen kunne ikke svare på den besked. Prøv at formulere den anderledes."}
            return

        if in_indre and buffer:
            indre_content += buffer
            yield {"type": "indre", "text": buffer}

        # If we never left indre mode, the model either skipped <indre> (show
        # the reply) or never closed it (strip_indre_tags removes it all).
        if not visible_content.strip():
            visible_content = strip_indre_tags(full_content)
            if not visible_content:
                logger.warning("No visible reply (stop_reason=%s)", final.stop_reason)
                yield {"type": "error", "text": "Personaen svarede ikke. Prøv at sende beskeden igen."}
                return
            yield {"type": "visible", "text": visible_content}

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


def sync_response(system_prompt: str, conversation_history: list[dict]) -> dict:
    """
    Non-streaming response for testing. Returns full and visible content.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = build_messages(conversation_history, prefill=False)

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=messages,
    )

    full_content = extract_text(response)
    visible_content = strip_indre_tags(full_content)

    return {
        "full_content": full_content,
        "visible_content": visible_content,
    }
