"""
Feedback system: extracts inner monologue, builds conversation context, generates feedback.
"""
import re
from pathlib import Path
from app.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, MAX_TOKENS, BASE_DIR, PERSONA_META
from app.database import get_session, get_messages, get_feedback, save_feedback
from app.prompt_assembler import parse_scenarios, get_briefing
import anthropic


def extract_indre_tags(content: str) -> str:
    """Extract the content within <indre>...</indre> tags. Returns empty string if not found."""
    match = re.search(r"<indre>(.*?)</indre>", content, re.DOTALL)
    return match.group(1).strip() if match else ""


async def reconstruct_conversation(session_id: str) -> list[dict]:
    """
    Reconstruct the conversation with <indre> tags extracted and labeled.

    Returns a list of exchange dicts with:
    - student: student's message
    - indre: inner monologue (if assistant response)
    - assistant: visible assistant response
    """
    messages = await get_messages(session_id)
    exchanges = []

    for i, msg in enumerate(messages):
        if msg["role"] == "user":
            # Start a new exchange with the student message
            current_exchange = {"student": msg["content"]}
        elif msg["role"] == "assistant":
            # This is the response to the most recent student message
            indre_content = extract_indre_tags(msg["content"])
            visible = msg["visible_content"] or re.sub(r"<indre>.*?</indre>\s*", "", msg["content"], flags=re.DOTALL).strip()

            current_exchange["indre"] = indre_content
            current_exchange["assistant"] = visible
            exchanges.append(current_exchange)

    return exchanges


async def build_feedback_prompt(session_id: str) -> str:
    """
    Build the full feedback prompt with template variables filled in.

    Returns the complete prompt ready for Claude API.
    """
    # Get session data
    session = await get_session(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    persona_id = session["persona_id"]
    scenario_number = session["scenario_number"]
    mission = session["mission"]

    # Get persona metadata
    persona_meta = PERSONA_META.get(persona_id)
    if not persona_meta:
        raise ValueError(f"Persona {persona_id} not found in metadata")

    persona_name = persona_meta["name"]
    persona_age = persona_meta["age"]

    # Get scenario data
    scenarios = parse_scenarios(persona_id)
    scenario = scenarios.get(scenario_number, {})
    scenario_name = scenario.get("title", f"Scenario {scenario_number}")

    # Read briefing for context
    briefing_data = get_briefing(persona_id, scenario_number)
    persona_context = briefing_data.get("persona_context", "")  # May be empty

    # Determine institution type from persona context
    institution_type = persona_meta.get("role", "socialpædagogisk praksis")

    # Build mission text
    mission_text = "Åben dialog"
    if mission:
        # Mission is just the mission ID (A/B/C), we'd need the full text from missions
        mission_text = f"Mission {mission}"

    # Reconstruct conversation with indre tags
    exchanges = await reconstruct_conversation(session_id)

    # Format conversation for the prompt
    samtale_lines = []
    for idx, exchange in enumerate(exchanges, 1):
        samtale_lines.append(f"UDVEKSLING {idx}:")
        samtale_lines.append(f'Student: "{exchange["student"]}"')
        if exchange.get("indre"):
            samtale_lines.append(f"<indre>\n{exchange['indre']}\n</indre>")
        samtale_lines.append(f'**{persona_name}:** "{exchange["assistant"]}"')
        samtale_lines.append("")  # Blank line between exchanges

    samtale_log = "\n".join(samtale_lines)

    # Load feedback prompt template
    template_path = BASE_DIR / "feedback_prompt.md"
    if not template_path.exists():
        raise FileNotFoundError(f"Feedback prompt template not found at {template_path}")

    template = template_path.read_text(encoding="utf-8")

    # Fill in template variables
    filled_prompt = template.replace("{{persona_navn}}", persona_name)
    filled_prompt = filled_prompt.replace("{{persona_alder}}", str(persona_age))
    filled_prompt = filled_prompt.replace("{{persona_kontekst}}", persona_context)
    filled_prompt = filled_prompt.replace("{{institution_type}}", institution_type)
    filled_prompt = filled_prompt.replace("{{scenario_navn}}", scenario_name)
    filled_prompt = filled_prompt.replace("{{mission_text}}", mission_text)
    filled_prompt = filled_prompt.replace("{{samtale_log}}", samtale_log)

    return filled_prompt


async def generate_feedback(session_id: str) -> str:
    """
    Generate feedback for a session using Claude API.

    Steps:
    1. Check if feedback already exists (return if it does)
    2. Build the feedback prompt
    3. Call Claude API
    4. Save to database
    5. Return feedback text

    Args:
        session_id: The session ID to generate feedback for

    Returns:
        The feedback text (markdown)

    Raises:
        ValueError if session not found
        anthropic.APIError if Claude API fails
    """
    # Check if feedback already exists
    existing = await get_feedback(session_id)
    if existing:
        return existing["content"]

    # Build prompt
    prompt = await build_feedback_prompt(session_id)

    # Call Claude API
    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )

    feedback_text = response.content[0].text

    # Save to database
    await save_feedback(session_id, feedback_text, status="generated")

    return feedback_text


def get_client() -> anthropic.AsyncAnthropic:
    """Create an async Anthropic client."""
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
