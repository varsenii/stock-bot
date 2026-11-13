"""
LLM backend implementations.

To add a new LLM provider (e.g. vLLM, llama.cpp HTTP, a cloud API):
  1. Create a module in this directory.
  2. Subclass ``BaseLLM`` and implement ``generate`` / ``is_available``.
  3. Wire it up in cli.py (or a future provider registry).
"""

from .base import BaseLLM
from .ollama import OllamaLLM

__all__ = ["BaseLLM", "OllamaLLM"]
