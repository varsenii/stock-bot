"""
Ollama LLM backend.

Talks to a locally-running Ollama server via the official ``ollama``
Python client.  The model must already be pulled
(``ollama pull <model>``) before first use.

Web search is handled externally by the Analyzer — this backend just
receives a prompt (already enriched with search results) and returns
the model's response.
"""

from __future__ import annotations

import logging

from ollama import Client, ResponseError

from ..config import LLMConfig
from .base import BaseLLM


class OllamaLLM(BaseLLM):
    """
    LLM backend that delegates to a local Ollama instance.

    Parameters
    ----------
    config:
        LLM settings (model name, host, generation params).
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._client = Client(host=config.host)

    # ------------------------------------------------------------------
    # BaseLLM interface
    # ------------------------------------------------------------------

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = self._client.chat(
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={
                "temperature": self._config.temperature,
                "num_predict": self._config.num_predict,
                "num_ctx": self._config.num_ctx,
            },
        )
        return response["message"]["content"]

    def is_available(self) -> bool:
        try:
            self._client.list()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ensure_model_pulled(self) -> None:
        """
        Check that the configured model is available locally.

        Raises
        ------
        RuntimeError
            If the model is not pulled or Ollama is unreachable.
        """
        try:
            response = self._client.list()
            model_names = [m.model for m in response.models]
            base = self._config.model.split(":")[0]
            if not any(base in n for n in model_names):
                raise RuntimeError(
                    f"Model '{self._config.model}' not found in Ollama. "
                    f"Pull it first:  ollama pull {self._config.model}"
                )
        except ResponseError as exc:
            raise RuntimeError(
                f"Cannot reach Ollama at {self._config.host}: {exc}"
            ) from exc
