"""
Prompt assembler: builds the final system prompt from persona files.

Reads the persona's system_prompt_v3.md template, parses the scenario file
for initial state values, and replaces all {{variables}}.
"""
import re
from pathlib import Path
from app.config import PERSONAS_DIR


def load_persona_file(persona_id: str, filename: str) -> str:
    """Load a persona file as string."""
    path = PERSONAS_DIR / persona_id / filename
    if not path.exists():
        raise FileNotFoundError(f"Persona file not found: {path}")
    return path.read_text(encoding="utf-8")


def parse_scenarios(persona_id: str) -> dict[int, dict]:
    """
    Parse scenarios_v2.md into a dict keyed by scenario number.

    Returns:
        {1: {"title": "...", "situation": "...", "tillid_niveau": "...",
              "tillid_begrundelse": "...", ...}, 2: {...}, ...}
    """
    content = load_persona_file(persona_id, "scenarios_v2.md")
    scenarios = {}

    # Split by scenario headers: ## Scenario N: Title
    scenario_blocks = re.split(r"(?=## Scenario \d+)", content)

    for block in scenario_blocks:
        # Match scenario header
        header_match = re.match(r"## Scenario (\d+):\s*(.+?)(?:\n|$)", block)
        if not header_match:
            continue

        num = int(header_match.group(1))
        title = header_match.group(2).strip()

        scenario = {"title": title, "number": num}

        # Extract niveau (progression level) if present
        niveau_match = re.search(
            r"\*\*Niveau:\*\*\s*(.+?)(?=\n\n|\n\*\*)", block, re.DOTALL
        )
        if niveau_match:
            raw = niveau_match.group(1).strip()
            # Split on em-dash or hyphen into label + description
            parts = re.split(r"\s*[—–-]\s*", raw, maxsplit=1)
            scenario["niveau_label"] = parts[0].strip()
            scenario["niveau_beskrivelse"] = parts[1].strip() if len(parts) > 1 else ""

        # Extract situation
        sit_match = re.search(
            r"\*\*Situation:\*\*\s*(.+?)(?=\n\n|\n\*\*)", block, re.DOTALL
        )
        if sit_match:
            scenario["situation"] = sit_match.group(1).strip()

        # Extract starttilstand values
        for axis in ["Tillid", "Aktivering", "Kapacitet"]:
            pattern = rf"-\s*{axis}:\s*(.+?)\s*—\s*(.+?)(?:\n|$)"
            match = re.search(pattern, block)
            if match:
                key = axis.lower()
                scenario[f"{key}_niveau"] = match.group(1).strip()
                scenario[f"{key}_begrundelse"] = match.group(2).strip()

        # Extract pædagogisk fokus (for student display)
        fokus_match = re.search(
            r"\*\*Pædagogisk fokus:\*\*\s*(.+?)(?=\n\n|\n\*\*)", block, re.DOTALL
        )
        if fokus_match:
            scenario["paedagogisk_fokus"] = fokus_match.group(1).strip()

        # Extract god tilgang
        tilgang_match = re.search(
            r"\*\*God tilgang:\*\*\s*(.+?)(?=\n\n|\n\*\*)", block, re.DOTALL
        )
        if tilgang_match:
            scenario["god_tilgang"] = tilgang_match.group(1).strip()

        # Extract typisk fejl
        fejl_match = re.search(
            r"\*\*Typisk fejl:\*\*\s*(.+?)(?=\n\n|\n\*\*)", block, re.DOTALL
        )
        if fejl_match:
            scenario["typisk_fejl"] = fejl_match.group(1).strip()

        # Extract dynamik
        dynamik_match = re.search(
            r"\*\*Dynamik i samtalen:\*\*\s*(.+?)(?=\n---|\Z)", block, re.DOTALL
        )
        if dynamik_match:
            scenario["dynamik"] = dynamik_match.group(1).strip()

        scenarios[num] = scenario

    return scenarios


def derive_scenario_goals(scenario: dict, persona_id: str) -> str:
    """
    Derive scenario-specific goals for the persona from the scenario context.
    These are the PERSONA's goals (what they want), not the student's learning goals.
    """
    situation = scenario.get("situation", "")
    dynamik = scenario.get("dynamik", "")

    # Build a contextual goal from the situation
    # This is deliberately general — the system prompt's BDI section
    # provides the strategic framework, and the scenario situation
    # gives the specific context. Together they generate realistic behavior.
    return f"Situationen: {situation}\n\nReager ud fra din personlighed og dine grundlæggende behov. Forfølg det der er vigtigst for dig i denne situation."


def derive_afslutningstype(scenario: dict) -> str:
    """
    Determine exit type based on activation level.
    High activation → brat afslutning possible.
    Otherwise → signaleret afslutning.
    """
    aktivering = scenario.get("aktivering_niveau", "").lower()
    if any(word in aktivering for word in ["meget høj", "høj"]):
        return "brat afslutning (ved alvorlige brud) eller signaleret afslutning"
    return "signaleret afslutning"


def assemble_system_prompt(persona_id: str, scenario_number: int) -> str:
    """
    Build the complete system prompt for a persona + scenario combination.

    1. Loads the system_prompt_v3.md template
    2. Parses the scenario for state values
    3. Replaces all {{variables}}
    4. Returns the final prompt string
    """
    # Load template
    template = load_persona_file(persona_id, "system_prompt_v3.md")

    # Parse scenarios
    scenarios = parse_scenarios(persona_id)
    if scenario_number not in scenarios:
        raise ValueError(
            f"Scenario {scenario_number} not found for {persona_id}. "
            f"Available: {list(scenarios.keys())}"
        )

    scenario = scenarios[scenario_number]

    # Build replacement map
    replacements = {
        "tillid_niveau": scenario.get("tillid_niveau", "Moderat"),
        "tillid_begrundelse": scenario.get("tillid_begrundelse", ""),
        "aktivering_niveau": scenario.get("aktivering_niveau", "Moderat"),
        "aktivering_begrundelse": scenario.get("aktivering_begrundelse", ""),
        "kapacitet_niveau": scenario.get("kapacitet_niveau", "Moderat"),
        "kapacitet_begrundelse": scenario.get("kapacitet_begrundelse", ""),
        "afslutningstype": derive_afslutningstype(scenario),
        "scenario_maal": derive_scenario_goals(scenario, persona_id),
        "scenario_situation": scenario.get("situation", ""),
    }

    # Replace all {{variables}} in template
    result = template
    for key, value in replacements.items():
        result = result.replace(f"{{{{{key}}}}}", value)

    return result


def get_briefing(persona_id: str, scenario_number: int) -> dict:
    """
    Build the student-facing briefing for a persona + scenario.

    Returns:
        {
            "briefing": str (overlevering + rolle + scenario-specifik rolle),
            "context": str (kontekst-elementer for efter samtalen)
        }
    """
    # Load studerende_tekster
    tekster = load_persona_file(persona_id, "studerende_tekster.md")

    # Load scenario-specific role description
    rollebeskrivelser = load_persona_file(persona_id, "rollebeskrivelser.md")

    # Find the right scenario role description
    rolle_blocks = re.split(r"(?=## Scenario \d+)", rollebeskrivelser)
    scenario_rolle = ""
    for block in rolle_blocks:
        match = re.match(rf"## Scenario {scenario_number}:", block)
        if match:
            # Remove the header line, keep the rest
            lines = block.split("\n", 1)
            scenario_rolle = lines[1].strip() if len(lines) > 1 else ""
            break

    # Replace {{scenario_rolle}} in tekster
    tekster = tekster.replace("{{scenario_rolle}}", scenario_rolle)

    # Split into briefing (before KONTEKST) and context (after)
    # Look for the context section marker
    context_markers = [
        "## KONTEKST-ELEMENTER",
        "## Kontekst-elementer",
        "## KONTEKST-KORT",
    ]

    briefing = tekster
    context = ""
    for marker in context_markers:
        if marker in tekster:
            parts = tekster.split(marker, 1)
            briefing = parts[0].strip()
            context = parts[1].strip()
            break

    return {"briefing": briefing, "context": context}


def get_missions(persona_id: str, scenario_number: int) -> list[dict]:
    """
    Get the three missions for a scenario.

    Returns:
        [{"id": "A", "text": "..."}, {"id": "B", "text": "..."}, {"id": "C", "text": "..."}]
    """
    content = load_persona_file(persona_id, "missioner.md")

    # Find the right scenario block
    scenario_blocks = re.split(r"(?=## Scenario \d+)", content)

    for block in scenario_blocks:
        match = re.match(rf"## Scenario {scenario_number}:", block)
        if match:
            missions = []
            for letter in ["A", "B", "C"]:
                # Support both "Mission A:" and "Opgave A:" formats
                pattern = rf"\*\*(?:Mission|Opgave) {letter}:\*\*\s*(.+?)(?=\n\n|\n\*\*|\Z)"
                m = re.search(pattern, block, re.DOTALL)
                if m:
                    missions.append({"id": letter, "text": m.group(1).strip()})
            return missions

    return []


def get_scenario_list(persona_id: str) -> list[dict]:
    """
    Get a summary list of all scenarios for a persona.

    Returns:
        [{"number": 1, "title": "Første møde", "situation": "...", "fokus": "..."}, ...]
    """
    scenarios = parse_scenarios(persona_id)
    return [
        {
            "number": num,
            "title": s["title"],
            "situation": s.get("situation", ""),
            "fokus": s.get("paedagogisk_fokus", ""),
            "niveau_label": s.get("niveau_label", ""),
            "niveau_beskrivelse": s.get("niveau_beskrivelse", ""),
        }
        for num, s in sorted(scenarios.items())
    ]
