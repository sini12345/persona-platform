"""
Tests for <indre> parsing and stop_reason handling in app/claude_client.py.

Runs without the API: the Anthropic client is replaced by a fake stream.

Usage:
    python tests/test_claude_client.py
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import claude_client  # noqa: E402


class FakeStream:
    def __init__(self, chunks, stop_reason, category=None):
        self.chunks = chunks
        self.final = SimpleNamespace(
            stop_reason=stop_reason,
            stop_details=SimpleNamespace(category=category) if category else None,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    async def text_stream(self):
        for chunk in self.chunks:
            yield chunk

    async def get_final_message(self):
        return self.final


def run(chunks, stop_reason="end_turn", category=None):
    fake = FakeStream(chunks, stop_reason, category)
    claude_client.get_client = lambda: SimpleNamespace(
        messages=SimpleNamespace(stream=lambda **kwargs: fake)
    )

    async def collect():
        return [e async for e in claude_client.stream_response("system", [])]

    events = asyncio.run(collect())
    shown = "".join(e["text"] for e in events if e["type"] == "visible")
    errors = [e["text"] for e in events if e["type"] == "error"]
    return shown, errors


def test_normal_reply():
    shown, errors = run(["<indre>Maven spænder.", "</indre>", " Hej."])
    assert shown.strip() == "Hej.", shown
    assert not errors


def test_unclosed_indre_does_not_leak():
    # Cut off (max_tokens) or model forgot </indre>: nothing of it may be shown.
    shown, errors = run(["<indre>Jeg stoler ikke på dem. ", "Hash er det eneste"], "max_tokens")
    assert "stoler" not in shown and "<indre>" not in shown, shown
    assert errors


def test_reply_without_indre_is_shown():
    shown, errors = run(["Hej med dig."])
    assert shown == "Hej med dig.", shown
    assert not errors


def test_refusal_gives_error_not_empty_reply():
    shown, errors = run([], "refusal", "general_harms")
    assert errors, "refusal must surface as an error"


def test_refusal_mid_stream_gives_error():
    shown, errors = run(["<indre>x</indre> Det startede"], "refusal")
    assert errors


def test_strip_indre_tags():
    s = claude_client.strip_indre_tags
    assert s("<indre>a</indre> hej") == "hej"
    assert s("<indre>a\nb") == ""
    assert s("<indre>a</indre> hej <indre>b") == "hej"
    assert s("hej") == "hej"


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"✅ {name}")
            except AssertionError as e:
                failed += 1
                print(f"❌ {name}: {e}")
    sys.exit(1 if failed else 0)
