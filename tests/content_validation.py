"""
Content Validation — Structural integrity checks for persona content files.

Validates that all personas have complete and consistent:
- system_prompt_v3.md (with required template variables)
- scenarios_v2.md (6 scenarios with 3-axis state definitions)
- missioner.md (A/B/C missions per scenario)
- studerende_tekster.md
- rollebeskrivelser.md

Usage:
    python tests/content_validation.py              # Run all checks
    python tests/content_validation.py --persona sara  # Check one persona
    python tests/content_validation.py --json       # JSON output for CI
"""

import re
import sys
import json
import argparse
from pathlib import Path
from dataclasses import dataclass

PERSONAS = ['mika', 'sara', 'bent', 'louise', 'peter', 'ali', 'yasmin']
BASE = Path(__file__).parent.parent / "personas"

REQUIRED_FILES = [
    'system_prompt_v3.md',
    'scenarios_v2.md',
    'missioner.md',
    'profil.md',
    'studerende_tekster.md',
    'rollebeskrivelser.md',
]

TEMPLATE_VARS = [
    '{{tillid_niveau}}',
    '{{tillid_begrundelse}}',
    '{{aktivering_niveau}}',
    '{{aktivering_begrundelse}}',
    '{{kapacitet_niveau}}',
    '{{kapacitet_begrundelse}}',
    '{{afslutningstype}}',
    '{{scenario_maal}}',
    '{{scenario_situation}}',
]

@dataclass
class Check:
    persona: str
    category: str
    description: str
    passed: bool
    details: str = ""

def check_files_exist(persona: str) -> list[Check]:
    """Check all required files exist for persona."""
    results = []
    persona_dir = BASE / persona
    for fname in REQUIRED_FILES:
        path = persona_dir / fname
        results.append(Check(
            persona=persona,
            category="files",
            description=f"{fname} exists",
            passed=path.exists(),
            details="" if path.exists() else f"Missing: {path}",
        ))
    return results

def check_template_vars(persona: str) -> list[Check]:
    """Check system prompt contains all 9 template variables."""
    results = []
    prompt_path = BASE / persona / "system_prompt_v3.md"
    if not prompt_path.exists():
        return [Check(persona, "template", "system_prompt_v3.md readable", False, "File missing")]

    content = prompt_path.read_text()
    for var in TEMPLATE_VARS:
        results.append(Check(
            persona=persona,
            category="template",
            description=f"Contains {var}",
            passed=var in content,
            details="" if var in content else f"Missing template variable: {var}",
        ))
    return results

def check_indre_instructions(persona: str) -> list[Check]:
    """Check system prompt has <indre>-tag instructions."""
    prompt_path = BASE / persona / "system_prompt_v3.md"
    if not prompt_path.exists():
        return [Check(persona, "indre", "system_prompt_v3.md readable", False, "File missing")]

    content = prompt_path.read_text().lower()
    checks = [
        ("Mentions <indre> tag", '<indre>' in content),
        ("Mentions body-first rule", any(w in content for w in ['krop', 'maven', 'bryst', 'skuldr', 'kæbe'])),
        ("Has SIGER ALDRIG section", 'siger aldrig' in content),
    ]
    return [Check(persona, "indre", desc, passed, "" if passed else f"Missing in system prompt")
            for desc, passed in checks]

def check_scenarios(persona: str) -> list[Check]:
    """Check scenarios file has proper structure."""
    results = []
    scenarios_path = BASE / persona / "scenarios_v2.md"
    if not scenarios_path.exists():
        return [Check(persona, "scenarios", "scenarios_v2.md readable", False, "File missing")]

    content = scenarios_path.read_text()

    # Count scenario headers (## Scenario N: or ## Scenarie N: - both spellings)
    scenario_headers = re.findall(r'(?:^|\n)##\s+[Ss]cenari[eo]\s+(\d+)', content)
    num_scenarios = len(scenario_headers)
    results.append(Check(
        persona=persona,
        category="scenarios",
        description=f"Has ≥6 scenarios (found {num_scenarios})",
        passed=num_scenarios >= 6,
        details=f"Found {num_scenarios} scenarios" if num_scenarios < 6 else "",
    ))

    # Check for 3-axis state definitions
    axis_terms = ['tillid', 'aktivering', 'kapacitet']
    for term in axis_terms:
        count = len(re.findall(term, content, re.IGNORECASE))
        results.append(Check(
            persona=persona,
            category="scenarios",
            description=f"Contains '{term}' axis definitions (found {count})",
            passed=count >= 6,  # At least one per scenario
            details=f"Only {count} mentions — expected ≥6" if count < 6 else "",
        ))

    return results

def check_missions(persona: str) -> list[Check]:
    """Check missions file has A/B/C for each scenario."""
    results = []
    missions_path = BASE / persona / "missioner.md"
    if not missions_path.exists():
        return [Check(persona, "missions", "missioner.md readable", False, "File missing")]

    content = missions_path.read_text()

    # Check for scenario sections
    scenario_sections = re.findall(r'(?:^|\n)##\s+[Ss]cenari[eo]\s+(\d+)', content)
    results.append(Check(
        persona=persona,
        category="missions",
        description=f"Has mission sections for ≥6 scenarios (found {len(scenario_sections)})",
        passed=len(scenario_sections) >= 6,
        details="" if len(scenario_sections) >= 6 else f"Found {len(scenario_sections)} scenario sections",
    ))

    # Check for A/B/C pattern
    abc_pattern = re.findall(r'(?:opgave|mission)\s*[abc]', content, re.IGNORECASE)
    results.append(Check(
        persona=persona,
        category="missions",
        description=f"Has A/B/C missions (found {len(abc_pattern)} labels)",
        passed=len(abc_pattern) >= 12,  # At least 2 per scenario × 6
        details="" if len(abc_pattern) >= 12 else f"Found {len(abc_pattern)} A/B/C labels",
    ))

    return results

def check_prompt_length(persona: str) -> list[Check]:
    """Check prompt length is within reasonable bounds."""
    prompt_path = BASE / persona / "system_prompt_v3.md"
    if not prompt_path.exists():
        return [Check(persona, "length", "system_prompt_v3.md readable", False, "File missing")]

    lines = prompt_path.read_text().strip().split('\n')
    num_lines = len(lines)

    # After restructuring, prompts should be ~150-250 lines
    # Peter and Ali may still be longer (~600)
    is_restructured = persona not in []  # All are now restructured
    max_lines = 300 if is_restructured else 700

    return [Check(
        persona=persona,
        category="length",
        description=f"Prompt length: {num_lines} lines (max {max_lines})",
        passed=num_lines <= max_lines,
        details=f"Prompt is {num_lines} lines — consider restructuring" if num_lines > max_lines else "",
    )]


def run_all_checks(personas: list[str] = None) -> list[Check]:
    """Run all content validation checks."""
    if personas is None:
        personas = PERSONAS

    all_checks = []
    for p in personas:
        all_checks.extend(check_files_exist(p))
        all_checks.extend(check_template_vars(p))
        all_checks.extend(check_indre_instructions(p))
        all_checks.extend(check_scenarios(p))
        all_checks.extend(check_missions(p))
        all_checks.extend(check_prompt_length(p))

    return all_checks


def print_results(checks: list[Check]):
    """Print results grouped by persona."""
    personas = {}
    for c in checks:
        if c.persona not in personas:
            personas[c.persona] = []
        personas[c.persona].append(c)

    total_pass = sum(1 for c in checks if c.passed)
    total = len(checks)

    print(f"\n{'='*60}")
    print(f"CONTENT VALIDATION — {total_pass}/{total} checks passed")
    print(f"{'='*60}\n")

    for persona, p_checks in sorted(personas.items()):
        p_pass = sum(1 for c in p_checks if c.passed)
        p_total = len(p_checks)
        status = "✅" if p_pass == p_total else "⚠️"

        print(f"{status} {persona.upper()} — {p_pass}/{p_total}")
        for c in p_checks:
            icon = "  ✓" if c.passed else "  ✗"
            print(f"  {icon} [{c.category}] {c.description}")
            if not c.passed and c.details:
                print(f"      → {c.details}")
        print()

    # Category summary
    categories = {}
    for c in checks:
        if c.category not in categories:
            categories[c.category] = {'pass': 0, 'total': 0}
        categories[c.category]['total'] += 1
        if c.passed:
            categories[c.category]['pass'] += 1

    print("By category:")
    for cat, counts in sorted(categories.items()):
        print(f"  {cat}: {counts['pass']}/{counts['total']}")

    print(f"\n{'='*60}")
    if total_pass == total:
        print("ALL CHECKS PASSED ✅")
    else:
        print(f"ISSUES: {total - total_pass} ⚠️")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Content Validation — Structural integrity checks')
    parser.add_argument('--persona', type=str, help='Check one persona only')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    personas = [args.persona.lower()] if args.persona else None
    checks = run_all_checks(personas)

    if args.json:
        output = [{"persona": c.persona, "category": c.category,
                   "description": c.description, "passed": c.passed,
                   "details": c.details} for c in checks]
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print_results(checks)

    sys.exit(0 if all(c.passed for c in checks) else 1)
