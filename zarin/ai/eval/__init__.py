"""Copilot evaluation harness — reproducible, offline, deterministic-first.

Distinguishes four dimensions and never collapses them to one number:
  deterministic correctness · grounding quality · refusal safety · (language/usefulness = human).
"""
from .runner import run_eval

__all__ = ["run_eval"]
