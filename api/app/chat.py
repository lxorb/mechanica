"""STUB. Owner: chat agent.

Chat over one manual, grounded in its page text, streamed.
  answer(manual_id, messages) -> Iterator[str]  # SSE frames: {"type":"token","text"} ... {"type":"done","answer","citations":[{"page","quote"}],"usd","tokensIn","tokensSaved"}
Retrieval: get_index().query + store.pages -> page passages -> compress with The Token Company (app/ttc.py) -> OpenAI (settings.model_chat) with a system prompt that
forbids anything not in the passages and requires page citations like [p. 84]. The UI turns [p. N] into jumps into the Book screen.
"""

from collections.abc import Iterator


def answer(manual_id: str, messages: list[dict]) -> Iterator[str]:
    raise NotImplementedError
