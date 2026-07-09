from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.common import llm


def clear_groq_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GROQ_API_KEY", "GROQ_API_KEY1", "GROQ_API_KEY2", "GROQ_API_KEY3", "GROQ_API_KEYS", "GROQ_MODEL", "GROQ_REASONING_MODEL"):
        monkeypatch.setenv(name, "")


def test_groq_api_keys_are_ordered_and_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_groq_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "primary")
    monkeypatch.setenv("GROQ_API_KEY1", "backup-1")
    monkeypatch.setenv("GROQ_API_KEY2", "backup-1")
    monkeypatch.setenv("GROQ_API_KEYS", "backup-2,backup-3")

    assert llm.groq_api_key_items() == [
        ("GROQ_API_KEY", "primary"),
        ("GROQ_API_KEY1", "backup-1"),
        ("GROQ_API_KEYS[1]", "backup-2"),
        ("GROQ_API_KEYS[2]", "backup-3"),
    ]


def test_llm_client_prefers_reasoning_model(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_groq_env(monkeypatch)
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setenv("GROQ_REASONING_MODEL", "openai/gpt-oss-120b")

    assert llm.LLMClient().model_name == "openai/gpt-oss-120b"


def test_llm_client_defaults_to_reasoning_model(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_groq_env(monkeypatch)

    assert llm.LLMClient().model_name == "openai/gpt-oss-120b"


def test_llm_text_invocation_falls_back_to_next_key(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_groq_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "rate-limited")
    monkeypatch.setenv("GROQ_API_KEY1", "working")
    client = llm.LLMClient(model="unit-test-model")
    attempts: list[str] = []

    class FakeModel:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def invoke(self, messages):
            attempts.append(self.api_key)
            if self.api_key == "rate-limited":
                raise RuntimeError("429 rate limit")
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(client, "_model", lambda temperature, api_key: FakeModel(api_key))

    assert client.invoke_text("system", "human") == "ok"
    assert attempts == ["rate-limited", "working"]


def test_llm_text_invocation_does_not_fallback_on_parser_error(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_groq_env(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "primary")
    monkeypatch.setenv("GROQ_API_KEY1", "backup")
    client = llm.LLMClient(model="unit-test-model")
    attempts: list[str] = []

    class OutputParserException(Exception):
        pass

    class FakeModel:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def invoke(self, messages):
            attempts.append(self.api_key)
            raise OutputParserException("bad structured output")

    monkeypatch.setattr(client, "_model", lambda temperature, api_key: FakeModel(api_key))

    with pytest.raises(OutputParserException):
        client.invoke_text("system", "human")
    assert attempts == ["primary"]
