"""LLM client factory — Portkey mode or direct mode.

All extraction code calls build_llm_client() and never constructs a
provider client directly. Model selection belongs in Portkey config or
LLM_MODEL_DIRECT env var — never hardcoded here.
"""
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_llm_client() -> Any:
    """Return a client with a .chat.completions.create() interface."""
    mode = os.environ.get("LLM_MODE", "portkey")
    if mode == "portkey":
        return _build_portkey_client()
    elif mode == "direct":
        return _build_direct_client()
    else:
        raise ValueError(f"Unknown LLM_MODE: {mode!r}. Expected 'portkey' or 'direct'.")


def _build_portkey_client() -> Any:
    from portkey_ai import Portkey

    return Portkey(
        api_key=os.environ["PORTKEY_API_KEY"],
        config=os.environ["PORTKEY_CONFIG"],
    )


def _build_direct_client() -> Any:
    provider = os.environ.get("LLM_PROVIDER", "google").lower()
    model = os.environ.get("LLM_MODEL_DIRECT", "gemini-2.5-flash")

    if provider == "google":
        return _GoogleDirectClient(model=model)
    elif provider == "openai":
        return _OpenAIDirectClient(model=model)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Expected 'google' or 'openai'.")


class _ChatCompletionsProxy:
    """Thin proxy that exposes .chat.completions.create()."""

    def __init__(self, create_fn):
        self._create_fn = create_fn

    def create(self, **kwargs):
        return self._create_fn(**kwargs)


class _ChatProxy:
    def __init__(self, create_fn):
        self.completions = _ChatCompletionsProxy(create_fn)


class _GoogleDirectClient:
    """Wraps Google Generative AI SDK in an OpenAI-compatible interface."""

    def __init__(self, model: str):
        import google.generativeai as genai

        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self._model_name = model
        self._genai = genai
        self.chat = _ChatProxy(self._create)

    def _create(self, messages: list[dict], **kwargs) -> Any:
        model = self._genai.GenerativeModel(self._model_name)
        prompt = "\n".join(m["content"] for m in messages)
        response = model.generate_content(prompt)

        # Return an OpenAI-compatible response object
        class _Choice:
            class _Message:
                content: str

            message = _Message()

        choice = _Choice()
        choice.message.content = response.text

        class _Response:
            choices = [choice]

        return _Response()


class _OpenAIDirectClient:
    """Wraps the OpenAI SDK in a pass-through (already OpenAI-compatible)."""

    def __init__(self, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self._model = model
        self.chat = self._client.chat

    # Delegate all other attribute lookups to the underlying client
    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)
