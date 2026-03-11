"""Application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
PERSONAS_DIR = BASE_DIR / "personas"
# On Railway, mount a persistent volume at /data
# Locally, falls back to ./data/app.db
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "app.db"))

# API
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))

# Auth
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production")

# Persona metadata (display info for UI)
PERSONA_META = {
    "mika": {
        "name": "Mika",
        "age": 22,
        "pronouns": "de/dem",
        "short": "22 år. Psykisk belastning, rusmidler, ustabil bolig. Tester professionelle for ægthed.",
        "color": "purple",
        "role": "Socialpædagog, §85 bostøtte",
        "icon": "🔥",
    },
    "sara": {
        "name": "Sara",
        "age": 19,
        "pronouns": "hun/hende",
        "short": "19 år. Efterværn. Stille, tilbagetrukket. Navigerer overgangen til voksenlivet alene.",
        "color": "blue",
        "role": "Kontaktperson, efterværn §68",
        "icon": "🌊",
    },
    "bent": {
        "name": "Bent",
        "age": 74,
        "pronouns": "han/ham",
        "short": "74 år. Plejehjem. Høfligt lukket. Savner sin have og sin kone Inger.",
        "color": "green",
        "role": "Pædagog/sosu, plejehjem",
        "icon": "🌿",
    },
    "louise": {
        "name": "Louise",
        "age": 34,
        "pronouns": "hun/hende",
        "short": "34 år. Botilbud §108. Elsker rutiner. Reagerer på forandringer med krop, ikke ord.",
        "color": "amber",
        "role": "Pædagog, §108 botilbud",
        "icon": "🏠",
    },
    "peter": {
        "name": "Peter",
        "age": 41,
        "pronouns": "han/ham",
        "short": "41 år. Retspsykiatri. Kontrolleret, skarp. Forsvarer sin ret til fair behandling.",
        "color": "slate",
        "role": "Pædagog, retspsykiatrisk botilbud",
        "icon": "⚖️",
    },
    "ali": {
        "name": "Ali",
        "age": 22,
        "pronouns": "han/ham",
        "short": "22 år. Nørrebro. Humor og gadekoder. Har ikke bedt om hjælp — du opsøger ham.",
        "color": "orange",
        "role": "Gadeplansmedarbejder / opsøgende pædagog",
        "icon": "🌆",
    },
    "yasmin": {
        "name": "Yasmin",
        "age": 14,
        "pronouns": "hun/hende",
        "short": "14 år. 8. klasse. Tredjegenerations-dansk. Navigerer identitet med humor og skarphed.",
        "color": "rose",
        "role": "Skolepædagog i udskolingen",
        "icon": "✨",
    },
}
