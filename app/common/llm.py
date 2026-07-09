"""Centralized LLM client for the multi-agent workflow."""

from __future__ import annotations

import logging
import os
import re
from typing import TypeVar

from pydantic import BaseModel
from pydantic import ValidationError

from app.common.environment import load_env

DEFAULT_REASONING_MODEL = "openai/gpt-oss-120b"
DEFAULT_MODEL = DEFAULT_REASONING_MODEL
DEFAULT_MAX_RETRIES = 2

SchemaT = TypeVar("SchemaT", bound=BaseModel)
logger = logging.getLogger("app.llm")


def _append_key(items: list[tuple[str, str]], seen: set[str], name: str, value: str) -> None:
    cleaned = value.strip()
    if cleaned and cleaned not in seen:
        items.append((name, cleaned))
        seen.add(cleaned)


def groq_api_key_items() -> list[tuple[str, str]]:
    load_env()
    items: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in ("GROQ_API_KEY", "GROQ_API_KEY1", "GROQ_API_KEY2", "GROQ_API_KEY3"):
        _append_key(items, seen, name, os.getenv(name, ""))
    for index, value in enumerate(re.split(r"[,\n]", os.getenv("GROQ_API_KEYS", "")), start=1):
        _append_key(items, seen, f"GROQ_API_KEYS[{index}]", value)
    return items


def _is_parser_error(exc: Exception) -> bool:
    return isinstance(exc, ValidationError) or exc.__class__.__name__ in {"OutputParserException", "ValidationError"}


def _invoke_with_key_fallback(operation):
    key_items = groq_api_key_items()
    if not key_items:
        raise RuntimeError("GROQ_API_KEY is required for LLM-backed workflow processing.")

    failed: list[str] = []
    last_exc: Exception | None = None
    for key_name, api_key in key_items:
        try:
            return operation(api_key)
        except Exception as exc:
            if _is_parser_error(exc):
                raise
            failed.append(key_name)
            last_exc = exc
            logger.warning("groq_key_failed key=%s error=%s", key_name, exc.__class__.__name__)

    joined = ", ".join(failed) or "none"
    raise RuntimeError(f"All configured Groq API keys failed: {joined}. Last error: {last_exc}") from last_exc


class LLMClient:
    """Thin wrapper around the configured Groq chat model."""

    def __init__(self, *, model: str | None = None, max_retries: int = DEFAULT_MAX_RETRIES) -> None:
        load_env()
        self.model_name = (
            model
            or os.getenv("GROQ_REASONING_MODEL", "").strip()
            or os.getenv("GROQ_MODEL", "").strip()
            or DEFAULT_MODEL
        )
        self.max_retries = max_retries

    @staticmethod
    def enabled() -> bool:
        return bool(groq_api_key_items())

    def _model(self, temperature: float, api_key: str):
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=self.model_name,
            temperature=temperature,
            max_retries=self.max_retries,
            api_key=api_key,
        )

    def invoke_structured(
        self,
        system_prompt: str,
        human_prompt: str,
        schema: type[SchemaT],
        *,
        temperature: float = 0.0,
    ) -> SchemaT:
        def invoke(api_key: str):
            model = self._model(temperature, api_key).with_structured_output(schema)
            return model.invoke([("system", system_prompt), ("human", human_prompt)])

        payload = _invoke_with_key_fallback(invoke)
        if not isinstance(payload, schema):
            payload = schema.model_validate(payload)
        return payload

    def invoke_text(self, system_prompt: str, human_prompt: str, *, temperature: float = 0.2) -> str:
        def invoke(api_key: str):
            return self._model(temperature, api_key).invoke([("system", system_prompt), ("human", human_prompt)])

        result = _invoke_with_key_fallback(invoke)
        return str(getattr(result, "content", "")).strip()


_default_client = LLMClient()


def llm_enabled() -> bool:
    return LLMClient.enabled()


def invoke_structured(
    system_prompt: str,
    human_prompt: str,
    schema: type[SchemaT],
    *,
    temperature: float = 0.0,
) -> SchemaT:
    return _default_client.invoke_structured(system_prompt, human_prompt, schema, temperature=temperature)


def invoke_text(system_prompt: str, human_prompt: str, *, temperature: float = 0.2) -> str:
    return _default_client.invoke_text(system_prompt, human_prompt, temperature=temperature)
