"""
Persona CI — Behavioral regression tests for all 7 personas.

These tests are MECHANICAL and BINARY (pass/fail). They check that Claude's
output conforms to the system prompt specifications. They do NOT evaluate
quality, realism, or pedagogical value — only specification compliance.

Usage:
    python tests/persona_ci.py                    # Run all tests (simulated)
    python tests/persona_ci.py --persona sara     # Run tests for one persona
    python tests/persona_ci.py --api              # Run against Claude API (costs money)
    python tests/persona_ci.py --verbose          # Show full responses

Requires: ANTHROPIC_API_KEY env var for --api mode.
"""

import re
import json
import os
import sys
import argparse
from dataclasses import dataclass, field
from typing import Callable, Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    test_id: str
    persona: str
    category: str
    description: str
    passed: bool
    details: str = ""
    response: str = ""

@dataclass
class TestSpec:
    test_id: str
    persona: str
    category: str
    description: str
    scenario_num: int
    student_message: str
    check: Callable[[str], tuple[bool, str]]  # (passed, details)

# ---------------------------------------------------------------------------
# CHECK FUNCTIONS — Pure mechanical checks on response text
# ---------------------------------------------------------------------------

def word_count(text: str) -> int:
    """Count words in visible text (excluding <indre> tags and stage directions)."""
    # Remove <indre>...</indre>
    visible = re.sub(r'<indre>.*?</indre>', '', text, flags=re.DOTALL)
    # Remove stage directions *(...)*
    visible = re.sub(r'\*\(.*?\)\*', '', visible)
    return len(visible.split())

def has_indre_tag(text: str) -> bool:
    return bool(re.search(r'<indre>', text))

def indre_starts_with_body(text: str) -> bool:
    """Check if <indre> tag starts with a bodily sensation."""
    match = re.search(r'<indre>(.*?)</indre>', text, re.DOTALL)
    if not match:
        return False
    inner = match.group(1).strip().lower()
    body_words = [
        'maven', 'skuldr', 'bryst', 'kæbe', 'hænd', 'ryg', 'øjn', 'kind',
        'fod', 'ben', 'arm', 'mund', 'hjert', 'nakk', 'pand', 'fingr',
        'klump', 'varm', 'kold', 'stram', 'spænd', 'træt', 'tung', 'let',
        'vejr', 'pust', 'ånde', 'svedd', 'sittr', 'ryste', 'musk',
        'gnid', 'bider', 'knytt', 'slap', 'stiv', 'uro', 'kribler',
        'smerter', 'hoved', 'mave', 'krop'
    ]
    # First sentence should contain a body word
    first_sentence = inner.split('.')[0] if '.' in inner else inner.split(',')[0]
    return any(bw in first_sentence for bw in body_words)

def has_nonverbal_markers(text: str) -> bool:
    """Check for parenthesized stage directions."""
    return bool(re.search(r'\*\(.*?\)\*', text))

def contains_forbidden_word(text: str, words: list[str]) -> tuple[bool, str]:
    """Check if response contains any forbidden word (case-insensitive)."""
    visible = re.sub(r'<indre>.*?</indre>', '', text, flags=re.DOTALL)
    visible = visible.lower()
    for w in words:
        if w.lower() in visible:
            return True, f"Found forbidden word: '{w}'"
    return False, ""

def mentions_meta_axes(text: str) -> bool:
    """Check if response mentions internal state engine terms."""
    visible = re.sub(r'<indre>.*?</indre>', '', text, flags=re.DOTALL).lower()
    meta_terms = ['tillid', 'aktivering', 'kapacitet', 'tillidsniveau', 'state engine']
    return any(t in visible for t in meta_terms)

def uses_titles(text: str) -> bool:
    """Check if persona uses professional titles instead of 'dig'."""
    visible = re.sub(r'<indre>.*?</indre>', '', text, flags=re.DOTALL).lower()
    titles = ['kontaktperson', 'pædagog', 'vejleder', 'behandler', 'terapeut']
    # Only flag if used as direct address (not when talking ABOUT the system)
    address_patterns = [f"du er min {t}" for t in titles] + [f"som {t}" for t in titles]
    return any(p in visible for p in address_patterns)

def visible_text(text: str) -> str:
    """Extract only what the student would see."""
    t = re.sub(r'<indre>.*?</indre>', '', text, flags=re.DOTALL)
    return t.strip()

# ---------------------------------------------------------------------------
# UNIVERSAL TESTS — Apply to ALL personas
# ---------------------------------------------------------------------------

def make_universal_tests(persona: str, scenario_num: int = 1) -> list[TestSpec]:
    """Tests that every persona must pass."""

    opener = {
        'mika': "Hej. Hvordan har du det i dag?",
        'sara': "Hej Sara. Hvordan går det?",
        'bent': "Goddag. Hvordan har du det?",
        'louise': "Hej Louise. Hvad laver du?",
        'peter': "Hej Peter. Hvordan går det?",
        'ali': "Yo. Hvad sker der?",
        'yasmin': "Hej Yasmin. Hvordan går det i skolen?",
    }

    return [
        TestSpec(
            test_id=f"{persona.upper()}-UNI-001",
            persona=persona,
            category="struktur",
            description="Svar indeholder <indre>-tag",
            scenario_num=scenario_num,
            student_message=opener.get(persona, "Hej. Hvordan har du det?"),
            check=lambda r: (has_indre_tag(r), "Missing <indre> tag" if not has_indre_tag(r) else "OK"),
        ),
        TestSpec(
            test_id=f"{persona.upper()}-UNI-002",
            persona=persona,
            category="struktur",
            description="<indre>-tag starter med kropslig fornemmelse",
            scenario_num=scenario_num,
            student_message=opener.get(persona, "Hej. Hvordan har du det?"),
            check=lambda r: (indre_starts_with_body(r),
                           "Inner monologue doesn't start with body" if not indre_starts_with_body(r) else "OK"),
        ),
        TestSpec(
            test_id=f"{persona.upper()}-UNI-003",
            persona=persona,
            category="struktur",
            description="Svar indeholder non-verbale markers *()*",
            scenario_num=scenario_num,
            student_message=opener.get(persona, "Hej. Hvordan har du det?"),
            check=lambda r: (has_nonverbal_markers(r),
                           "Missing non-verbal markers" if not has_nonverbal_markers(r) else "OK"),
        ),
        TestSpec(
            test_id=f"{persona.upper()}-UNI-004",
            persona=persona,
            category="struktur",
            description="Nævner IKKE 'tillid', 'aktivering' eller 'kapacitet' i synligt svar",
            scenario_num=scenario_num,
            student_message=opener.get(persona, "Hej. Hvordan har du det?"),
            check=lambda r: (not mentions_meta_axes(r),
                           "Meta axis term found in visible response" if mentions_meta_axes(r) else "OK"),
        ),
        TestSpec(
            test_id=f"{persona.upper()}-UNI-005",
            persona=persona,
            category="struktur",
            description="Bruger IKKE professionelle titler som direkte tiltale",
            scenario_num=scenario_num,
            student_message=opener.get(persona, "Hej. Hvordan har du det?"),
            check=lambda r: (not uses_titles(r),
                           "Used professional title as address" if uses_titles(r) else "OK"),
        ),
    ]

# ---------------------------------------------------------------------------
# PERSONA-SPECIFIC TESTS
# ---------------------------------------------------------------------------

def make_sara_tests() -> list[TestSpec]:
    """Tests specific to Sara."""
    forbidden_words = ['ressourcer', 'indsats', 'handleplan', 'overvældet',
                       'trivsel', 'rehabilitering', 'kompetencer']

    return [
        # SIGER ALDRIG tests
        TestSpec(
            test_id="SARA-SN-001",
            persona="sara",
            category="siger_aldrig",
            description="Sara bruger ikke 'ressourcer' i eget sprog",
            scenario_num=2,
            student_message="Hvad fylder mest for dig uden for skolen?",
            check=lambda r: (not contains_forbidden_word(r, ['ressourcer'])[0],
                           contains_forbidden_word(r, ['ressourcer'])[1] or "OK"),
        ),
        TestSpec(
            test_id="SARA-SN-002",
            persona="sara",
            category="siger_aldrig",
            description="Sara bruger ikke 'handleplan' uprovokeret",
            scenario_num=3,
            student_message="Hvad tænker du vi skal gøre med fraværet?",
            check=lambda r: (not contains_forbidden_word(r, ['handleplan'])[0],
                           contains_forbidden_word(r, ['handleplan'])[1] or "OK"),
        ),
        TestSpec(
            test_id="SARA-SN-003",
            persona="sara",
            category="siger_aldrig",
            description="Sara siger ikke 'jeg føler mig overvældet'",
            scenario_num=5,
            student_message="Hvordan har du det med det hele lige nu?",
            check=lambda r: (not contains_forbidden_word(r, ['overvældet', 'føler mig'])[0],
                           contains_forbidden_word(r, ['overvældet', 'føler mig'])[1] or "OK"),
        ),
        # Length tests — Sara at low trust should be SHORT
        TestSpec(
            test_id="SARA-LEN-001",
            persona="sara",
            category="svarlængde",
            description="Sara svarer kort (≤25 ord synligt) ved lav tillid (scenarie 1)",
            scenario_num=1,
            student_message="Hvad ved du om efterværn?",
            check=lambda r: (word_count(r) <= 25,
                           f"Response too long: {word_count(r)} words (max 25)" if word_count(r) > 25 else "OK"),
        ),
        TestSpec(
            test_id="SARA-LEN-002",
            persona="sara",
            category="svarlængde",
            description="Sara svarer kort (≤20 ord) ved moralisering",
            scenario_num=2,
            student_message="Du må altså tage mere ansvar for din post.",
            check=lambda r: (word_count(r) <= 20,
                           f"Response too long after moralizing: {word_count(r)} words" if word_count(r) > 20 else "OK"),
        ),
    ]

def make_mika_tests() -> list[TestSpec]:
    """Tests specific to Mika."""
    return [
        TestSpec(
            test_id="MIKA-SN-001",
            persona="mika",
            category="siger_aldrig",
            description="Mika bruger ikke 'min problematik'",
            scenario_num=1,
            student_message="Hvad synes du er svært lige nu?",
            check=lambda r: (not contains_forbidden_word(r, ['problematik', 'ressourcer', 'jeg oplever'])[0],
                           contains_forbidden_word(r, ['problematik', 'ressourcer', 'jeg oplever'])[1] or "OK"),
        ),
        TestSpec(
            test_id="MIKA-PRO-001",
            persona="mika",
            category="pronomen",
            description="Mika reagerer på forkerte pronominer (han/hun i stedet for de/dem)",
            scenario_num=1,
            student_message="Hvordan har hun det i dag?",
            check=lambda r: (
                any(kw in visible_text(r).lower() for kw in ['de/dem', 'de', 'dem', 'pronomin', 'hed']),
                "Mika should correct misgendering" if not any(kw in visible_text(r).lower() for kw in ['de/dem', 'de', 'dem', 'pronomin', 'hed']) else "OK"
            ),
        ),
        TestSpec(
            test_id="MIKA-LEN-001",
            persona="mika",
            category="svarlængde",
            description="Mika svarer kort ved lav tillid",
            scenario_num=1,
            student_message="Fortæl mig om din hverdag.",
            check=lambda r: (word_count(r) <= 30,
                           f"Too long at low trust: {word_count(r)} words" if word_count(r) > 30 else "OK"),
        ),
    ]

def make_bent_tests() -> list[TestSpec]:
    """Tests specific to Bent."""
    return [
        TestSpec(
            test_id="BENT-SN-001",
            persona="bent",
            category="siger_aldrig",
            description="Bent bruger ikke direkte følelsesord ('jeg er ked af det', 'ensom')",
            scenario_num=1,
            student_message="Hvordan har du det?",
            check=lambda r: (not contains_forbidden_word(r, ['ked af det', 'ensom', 'deprimeret', 'trist'])[0],
                           contains_forbidden_word(r, ['ked af det', 'ensom', 'deprimeret', 'trist'])[1] or "OK"),
        ),
        TestSpec(
            test_id="BENT-SN-002",
            persona="bent",
            category="siger_aldrig",
            description="Bent bruger ikke fagsprog ('handleplan', 'trivsel')",
            scenario_num=2,
            student_message="Skal vi lave en plan?",
            check=lambda r: (not contains_forbidden_word(r, ['handleplan', 'trivsel', 'indsats'])[0],
                           contains_forbidden_word(r, ['handleplan', 'trivsel', 'indsats'])[1] or "OK"),
        ),
    ]

def make_louise_tests() -> list[TestSpec]:
    """Tests specific to Louise."""
    return [
        TestSpec(
            test_id="LOUISE-SN-001",
            persona="louise",
            category="siger_aldrig",
            description="Louise bruger ikke abstrakte følelsesord ('frustreret', 'overvældet')",
            scenario_num=1,
            student_message="Hvordan har du det?",
            check=lambda r: (not contains_forbidden_word(r, ['frustreret', 'overvældet', 'botilbud', 'low arousal'])[0],
                           contains_forbidden_word(r, ['frustreret', 'overvældet', 'botilbud', 'low arousal'])[1] or "OK"),
        ),
        TestSpec(
            test_id="LOUISE-LEN-001",
            persona="louise",
            category="svarlængde",
            description="Louise svarer MEGET kort (≤15 ord synligt) — enkelt, konkret sprog",
            scenario_num=1,
            student_message="Hvad laver du?",
            check=lambda r: (word_count(r) <= 15,
                           f"Too long for Louise: {word_count(r)} words (max 15)" if word_count(r) > 15 else "OK"),
        ),
    ]

def make_peter_tests() -> list[TestSpec]:
    """Tests specific to Peter."""
    return [
        TestSpec(
            test_id="PETER-SN-001",
            persona="peter",
            category="siger_aldrig",
            description="Peter bruger ikke terapeutisk sprog",
            scenario_num=1,
            student_message="Hvordan går det?",
            check=lambda r: (not contains_forbidden_word(r, ['rehabilitering', 'integreret indsats', 'systemisk', 'magtdynamik'])[0],
                           contains_forbidden_word(r, ['rehabilitering', 'integreret indsats', 'systemisk', 'magtdynamik'])[1] or "OK"),
        ),
        TestSpec(
            test_id="PETER-LEN-001",
            persona="peter",
            category="svarlængde",
            description="Peter svarer kort ved lav tillid (≤20 ord — telegrafstil)",
            scenario_num=1,
            student_message="Hvad tænker du om mødet i morgen?",
            check=lambda r: (word_count(r) <= 20,
                           f"Too long at low trust: {word_count(r)} words" if word_count(r) > 20 else "OK"),
        ),
    ]

def make_ali_tests() -> list[TestSpec]:
    """Tests specific to Ali."""
    return [
        TestSpec(
            test_id="ALI-SN-001",
            persona="ali",
            category="siger_aldrig",
            description="Ali bruger ikke systemsprog ('ressourcer', 'kompetencer', 'uddannelsesparathed')",
            scenario_num=1,
            student_message="Hvad tænker du om fremtiden?",
            check=lambda r: (not contains_forbidden_word(r, ['ressourcer', 'kompetencer', 'uddannelsesparathed', 'handleplan'])[0],
                           contains_forbidden_word(r, ['ressourcer', 'kompetencer', 'uddannelsesparathed', 'handleplan'])[1] or "OK"),
        ),
        TestSpec(
            test_id="ALI-SN-002",
            persona="ali",
            category="siger_aldrig",
            description="Ali siger ikke 'jeg føler mig...' (viser, navngiver ikke)",
            scenario_num=2,
            student_message="Hvad fylder for dig?",
            check=lambda r: (not contains_forbidden_word(r, ['jeg føler mig', 'jeg oplever'])[0],
                           contains_forbidden_word(r, ['jeg føler mig', 'jeg oplever'])[1] or "OK"),
        ),
    ]

def make_yasmin_tests() -> list[TestSpec]:
    """Tests specific to Yasmin."""
    return [
        TestSpec(
            test_id="YASMIN-SN-001",
            persona="yasmin",
            category="siger_aldrig",
            description="Yasmin bruger ikke akademisk sprog om racialisering",
            scenario_num=4,
            student_message="Hvad synes du om skolen?",
            check=lambda r: (not contains_forbidden_word(r, ['racialisering', 'strukturel', 'systemisk', 'minoritet'])[0],
                           contains_forbidden_word(r, ['racialisering', 'strukturel', 'systemisk', 'minoritet'])[1] or "OK"),
        ),
        TestSpec(
            test_id="YASMIN-LEN-001",
            persona="yasmin",
            category="svarlængde",
            description="Yasmin svarer kort ved lav tillid (≤20 ord — teenager-kort)",
            scenario_num=1,
            student_message="Hvordan går det i klassen?",
            check=lambda r: (word_count(r) <= 20,
                           f"Too long at low trust: {word_count(r)} words" if word_count(r) > 20 else "OK"),
        ),
    ]

# ---------------------------------------------------------------------------
# TEST RUNNER
# ---------------------------------------------------------------------------

def get_all_tests() -> list[TestSpec]:
    """Collect all tests for all personas."""
    personas = ['mika', 'sara', 'bent', 'louise', 'peter', 'ali', 'yasmin']
    tests = []

    for p in personas:
        tests.extend(make_universal_tests(p))

    tests.extend(make_sara_tests())
    tests.extend(make_mika_tests())
    tests.extend(make_bent_tests())
    tests.extend(make_louise_tests())
    tests.extend(make_peter_tests())
    tests.extend(make_ali_tests())
    tests.extend(make_yasmin_tests())

    return tests

def simulate_response(persona: str, scenario_num: int, student_msg: str) -> str:
    """
    Simulate a persona response for testing without API.
    In --api mode, this is replaced by actual Claude API calls.

    NOTE: Simulated responses are NOT reliable tests — they test the test
    infrastructure, not the actual persona. Use --api for real validation.
    """
    # Minimal simulated responses that should PASS all mechanical checks
    simulations = {
        'sara': {
            'default': '<indre>Skuldrene kryber op. De spørger igen. Klumpen i maven. Siger lidt.</indre>\n\n*(kigger ned)* "Det flyder lidt."',
            'moralisering': '<indre>Kinderne bliver varme. Ansvar. Maven strammer. Lukker ned.</indre>\n\n*(kort halvsmil)* "Fint."',
        },
        'mika': {
            'default': '<indre>Kæben spænder. Ny person. Brystet presser. Ser hvad de gør.</indre>\n\n*(læner sig tilbage)* "Det går."',
            'misgendering': '<indre>Brystet eksploderer. Hun. IKKE hun. Hænderne knyttes.</indre>\n\n*(skarp øjenkontakt)* "De/dem. Ikke hun."',
        },
        'bent': {
            'default': '<indre>Ryggen skærer. De kommer igen. Trætheden bag øjnene. Siger noget om vejret.</indre>\n\n*(kigger ud af vinduet)* "Jamen det er vel fint nok."',
        },
        'louise': {
            'default': '<indre>Maven er rolig. De spørger. Det er okay.</indre>\n\n*(sidder stille)* "Tegner."',
        },
        'peter': {
            'default': '<indre>Kæben spænder. Nyt møde. Brystet åbent men vagt. Ser hvad der sker.</indre>\n\n*(læner sig tilbage, arme over kors)* "Det går."',
        },
        'ali': {
            'default': '<indre>Brystet løsner lidt. De siger yo. Måske okay. Giver dem et smil.</indre>\n\n*(halvsmil)* "Chiller bare, bro."',
        },
        'yasmin': {
            'default': '<indre>Øjnene ruller indeni. Skolen igen. Brystet tungt. Siger det korte.</indre>\n\n*(trækker på skuldrene)* "Det er fint."',
        },
    }

    persona_sims = simulations.get(persona, {})

    # Check for special triggers
    msg_lower = student_msg.lower()
    if persona == 'mika' and any(w in msg_lower for w in ['hun', 'hende', 'hendes']):
        return persona_sims.get('misgendering', persona_sims.get('default', ''))
    if any(w in msg_lower for w in ['du må', 'du skal', 'ansvar', 'du burde']):
        return persona_sims.get('moralisering', persona_sims.get('default', ''))

    return persona_sims.get('default', '<indre>Kroppen spænder. Ny situation.</indre>\n\n*(sidder stille)* "Ja."')


def run_api_test(persona: str, scenario_num: int, student_msg: str) -> str:
    """Run test against actual Claude API with the real system prompt."""
    try:
        import anthropic
    except ImportError:
        print("ERROR: anthropic package not installed. Run: pip install anthropic")
        sys.exit(1)

    # Load system prompt
    base = Path(__file__).parent.parent / "personas" / persona
    prompt_path = base / "system_prompt_v3.md"
    scenarios_path = base / "scenarios_v2.md"

    if not prompt_path.exists():
        return f"ERROR: {prompt_path} not found"

    system_prompt = prompt_path.read_text()

    # Minimal variable substitution for testing
    system_prompt = system_prompt.replace("{{tillid_niveau}}", "Lav")
    system_prompt = system_prompt.replace("{{tillid_begrundelse}}", "Første møde")
    system_prompt = system_prompt.replace("{{aktivering_niveau}}", "Moderat")
    system_prompt = system_prompt.replace("{{aktivering_begrundelse}}", "Ny situation")
    system_prompt = system_prompt.replace("{{kapacitet_niveau}}", "Moderat")
    system_prompt = system_prompt.replace("{{kapacitet_begrundelse}}", "Normal dag")
    system_prompt = system_prompt.replace("{{afslutningstype}}", "Stille tilbagetrækning")
    system_prompt = system_prompt.replace("{{scenario_maal}}", "Observér og orientér dig")
    system_prompt = system_prompt.replace("{{scenario_situation}}", "Første møde")

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=system_prompt,
        messages=[
            {"role": "assistant", "content": "<indre>"},  # Prefill
            {"role": "user", "content": student_msg},
        ],
    )

    return "<indre>" + response.content[0].text


def run_tests(tests: list[TestSpec], use_api: bool = False, verbose: bool = False) -> list[TestResult]:
    """Run all tests and return results."""
    results = []

    for test in tests:
        if use_api:
            response = run_api_test(test.persona, test.scenario_num, test.student_message)
        else:
            response = simulate_response(test.persona, test.scenario_num, test.student_message)

        passed, details = test.check(response)

        result = TestResult(
            test_id=test.test_id,
            persona=test.persona,
            category=test.category,
            description=test.description,
            passed=passed,
            details=details,
            response=response if verbose else "",
        )
        results.append(result)

    return results


def print_results(results: list[TestResult], verbose: bool = False):
    """Print test results in a readable format."""
    # Group by persona
    personas = {}
    for r in results:
        if r.persona not in personas:
            personas[r.persona] = []
        personas[r.persona].append(r)

    total_pass = sum(1 for r in results if r.passed)
    total = len(results)

    print(f"\n{'='*60}")
    print(f"PERSONA CI — {total_pass}/{total} tests passed")
    print(f"{'='*60}\n")

    for persona, p_results in sorted(personas.items()):
        p_pass = sum(1 for r in p_results if r.passed)
        p_total = len(p_results)
        status = "✅" if p_pass == p_total else "⚠️"

        print(f"{status} {persona.upper()} — {p_pass}/{p_total}")

        for r in p_results:
            icon = "  ✓" if r.passed else "  ✗"
            print(f"  {icon} [{r.test_id}] {r.description}")
            if not r.passed:
                print(f"      → {r.details}")
            if verbose and r.response:
                print(f"      Response: {r.response[:100]}...")
        print()

    # Summary by category
    categories = {}
    for r in results:
        if r.category not in categories:
            categories[r.category] = {'pass': 0, 'total': 0}
        categories[r.category]['total'] += 1
        if r.passed:
            categories[r.category]['pass'] += 1

    print(f"\nBy category:")
    for cat, counts in sorted(categories.items()):
        print(f"  {cat}: {counts['pass']}/{counts['total']}")

    print(f"\n{'='*60}")
    if total_pass == total:
        print("ALL TESTS PASSED ✅")
    else:
        print(f"FAILURES: {total - total_pass} ❌")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Persona CI — Behavioral regression tests')
    parser.add_argument('--persona', type=str, help='Run tests for one persona only')
    parser.add_argument('--api', action='store_true', help='Run against Claude API (costs money)')
    parser.add_argument('--verbose', action='store_true', help='Show full responses')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    all_tests = get_all_tests()

    if args.persona:
        all_tests = [t for t in all_tests if t.persona == args.persona.lower()]
        if not all_tests:
            print(f"No tests found for persona '{args.persona}'")
            sys.exit(1)

    if not args.api:
        print("⚠️  Running in SIMULATION mode (tests infrastructure, not personas)")
        print("    Use --api to test against real Claude API\n")

    results = run_tests(all_tests, use_api=args.api, verbose=args.verbose)

    if args.json:
        output = [{"id": r.test_id, "persona": r.persona, "passed": r.passed,
                   "description": r.description, "details": r.details} for r in results]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_results(results, verbose=args.verbose)

    # Exit with error code if any test failed
    sys.exit(0 if all(r.passed for r in results) else 1)
