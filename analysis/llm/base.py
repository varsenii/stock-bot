"""
Abstract base class for LLM backends.

Any module that talks to a language model (Ollama, vLLM, a REST API, …)
implements this interface so the rest of the analysis pipeline stays
provider-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """Minimal contract every LLM backend must fulfil."""

    @abstractmethod
    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """
        Send a single-turn (system + user) prompt and return the final
        response text.

        Implementations may perform multiple rounds of tool calling
        (e.g. web search) internally before returning the answer.

        Parameters
        ----------
        system_prompt:
            Instructions that set the model's behaviour / persona.
        user_prompt:
            The concrete question or task for this turn.

        Returns
        -------
        str
            The model's final response.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if the backend is reachable and ready to serve."""
        ...
