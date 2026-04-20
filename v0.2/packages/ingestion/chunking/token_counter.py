"""Simple token count estimation.

Uses word count with a 1.3 tokens-per-word heuristic (English text averages
~1.3 tokens per whitespace-delimited word across common tokenizers).
Avoids a tiktoken dependency while staying accurate enough for 400-800 target windows.
"""

from __future__ import annotations

TOKENS_PER_WORD = 1.3


def estimate_tokens(text: str) -> int:
    """Estimate token count from text."""
    words = text.split()
    return int(len(words) * TOKENS_PER_WORD)
