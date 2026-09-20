"""STUB. Owner: chat agent. The Token Company middleware (https://thetokencompany.com/docs).

compress(text, aggressiveness=0.3, route="chat") -> (compressed_text, original_tokens, output_tokens)
Sits between PDF page text and every LLM call (chat and ask picker). No key -> returns the text unchanged.
Logs saved tokens per route so /cost can report them.
"""

from .config import settings


def compress(text: str, aggressiveness: float = 0.3, route: str = "chat") -> tuple[str, int, int]:
    if not settings.ttc_api_key:
        return text, 0, 0
    raise NotImplementedError
