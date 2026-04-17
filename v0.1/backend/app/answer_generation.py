from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import json
import logging
import re

import httpx

from app.settings import settings
from rag.types import SearchResult

_SOURCE_RE = re.compile(r"\[source\s+(\d+)\]", re.IGNORECASE)
_INLINE_SOURCE_RE = re.compile(r"\[source\s+(\d+)\](?!\()", re.IGNORECASE)
_INSUFFICIENT_RE = re.compile(
    r"\b(not enough evidence|insufficient evidence|cannot determine|can't determine|don't have enough evidence)\b",
    re.IGNORECASE,
)
_LOGGER = logging.getLogger(__name__)


def _sanitize_single_line(text: str) -> str:
    first_line = ""
    for line in text.splitlines():
        candidate = line.strip()
        if candidate:
            first_line = candidate
            break
    cleaned = first_line.strip().strip("`\"'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


@dataclass(slots=True)
class OllamaChatAdapter:
    base_url: str
    model: str
    timeout_s: float

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        endpoint = self.base_url.rstrip("/") + "/api/generate"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            _LOGGER.warning("Ollama non-stream completion failed: %s", exc)
            return ""
        return str(data.get("response", "")).strip()

    def stream_complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> Iterator[str]:
        payload = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        endpoint = self.base_url.rstrip("/") + "/api/generate"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                with client.stream("POST", endpoint, json=payload) as response:
                    response.raise_for_status()
                    for raw_line in response.iter_lines():
                        line = raw_line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                        except (TypeError, ValueError):
                            _LOGGER.debug("Ignoring non-JSON Ollama stream chunk")
                            continue

                        if "error" in chunk:
                            _LOGGER.warning("Ollama stream returned error chunk: %s", chunk.get("error"))
                            continue

                        delta = str(chunk.get("response", ""))
                        if delta:
                            yield delta
        except httpx.HTTPError as exc:
            _LOGGER.warning("Ollama stream request failed: %s", exc)

    def health_status(self) -> dict[str, object]:
        endpoint = self.base_url.rstrip("/") + "/api/tags"
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.get(endpoint)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            return {
                "backend": "ollama",
                "ok": False,
                "model": self.model,
                "available_models": [],
                "detail": f"health check failed: {exc}",
            }

        models = data.get("models") or []
        names = [str(item.get("name", "")) for item in models]
        model_ok = any(name == self.model or name.startswith(f"{self.model}:") for name in names)

        return {
            "backend": "ollama",
            "ok": model_ok,
            "model": self.model,
            "available_models": names,
            "detail": "model available" if model_ok else "model not found in ollama tags",
        }


class GroundedAnswerGenerator:
    def __init__(self, adapter: OllamaChatAdapter) -> None:
        self._adapter = adapter

    def system_prompt_for_debug(self) -> str:
        return self._system_prompt()

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a grounded QA assistant. "
            "Answer only from the provided evidence. "
            "If evidence is partially relevant, provide the partial answer and clearly state what is missing. "
            "Say 'Insufficient evidence.' only when no relevant fact is present in the evidence. "
            "Whenever you use a fact, cite it as a markdown link in the format [source N](URL)."
        )

    @staticmethod
    def _normalized_snippet(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _select_evidence(self, results: list[SearchResult]) -> list[SearchResult]:
        ordered = sorted(results, key=lambda item: item.score, reverse=True)
        if not ordered:
            return []

        selected: list[SearchResult] = []
        seen_keys: set[tuple[str, str]] = set()
        total_chars = 0

        for candidate in ordered:
            if len(selected) >= settings.answer_generation_context_k:
                break

            dedupe_key = (candidate.url, candidate.heading)
            if dedupe_key in seen_keys:
                continue

            snippet_len = min(
                len(self._normalized_snippet(candidate.text)),
                settings.answer_generation_max_chunk_chars,
            )

            # Keep at least one chunk, then enforce a total evidence-character budget.
            if selected and (total_chars + snippet_len) > settings.answer_generation_max_evidence_chars:
                break

            selected.append(candidate)
            seen_keys.add(dedupe_key)
            total_chars += snippet_len

        if selected:
            return selected

        return ordered[:1]

    def _user_prompt(self, question: str, evidence: list[SearchResult]) -> str:
        lines = [
            "Question:",
            question.strip(),
            "",
            "Evidence:",
        ]

        if not evidence:
            lines.append("(none)")
            lines.append("")
        else:
            for idx, result in enumerate(evidence, start=1):
                snippet = self._normalized_snippet(result.text)
                if len(snippet) > settings.answer_generation_max_chunk_chars:
                    snippet = snippet[: settings.answer_generation_max_chunk_chars] + "..."
                lines.extend(
                    [
                        f"[source {idx}]",
                        f"URL: {result.url}",
                        f"Domain: {result.domain}",
                        f"Heading: {result.heading}",
                        f"Text: {snippet}",
                        "",
                    ]
                )

        lines.extend(
            [
                "Rules:",
                "- Use only evidence above.",
                "- Include citations in-line as markdown links: [source N](URL).",
                "- If at least one relevant fact exists, answer with those facts and cite them.",
                "- Say 'Insufficient evidence.' only when none of the evidence is relevant.",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _linkify_citations(answer: str, source_map: dict[int, SearchResult]) -> str:
        def _replace(match: re.Match[str]) -> str:
            source = int(match.group(1))
            result = source_map.get(source)
            if result is None:
                return match.group(0)
            return f"[source {source}]({result.url})"

        return _INLINE_SOURCE_RE.sub(_replace, answer)

    @staticmethod
    def _final_payload(answer: str, source_map: dict[int, SearchResult]) -> dict[str, object]:
        linked_answer = GroundedAnswerGenerator._linkify_citations(answer.strip(), source_map)
        cited = sorted({int(match) for match in _SOURCE_RE.findall(linked_answer) if int(match) in source_map})

        insufficient = bool(_INSUFFICIENT_RE.search(linked_answer)) or not source_map
        citations = [] if insufficient else [
            {
                "source": source,
                "url": source_map[source].url,
                "domain": source_map[source].domain,
                "heading": source_map[source].heading,
                "score": round(source_map[source].score, 4),
                "chunk_id": source_map[source].chunk_id,
            }
            for source in cited
        ]

        return {
            "answer": linked_answer,
            "insufficient_evidence": insufficient,
            "citations": citations,
        }

    def generate(self, question: str, results: list[SearchResult]) -> dict[str, object]:
        evidence = self._select_evidence(results)
        source_map = {idx: item for idx, item in enumerate(evidence, start=1)}

        answer = self._adapter.complete(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(question, evidence),
            temperature=settings.answer_generation_temperature,
            max_tokens=settings.answer_generation_max_tokens,
        )
        if not answer:
            answer = "Insufficient evidence."

        return self._final_payload(answer, source_map)

    def stream_generate(self, question: str, results: list[SearchResult]) -> Iterator[dict[str, object]]:
        evidence = self._select_evidence(results)
        source_map = {idx: item for idx, item in enumerate(evidence, start=1)}

        parts: list[str] = []
        for delta in self._adapter.stream_complete(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(question, evidence),
            temperature=settings.answer_generation_temperature,
            max_tokens=settings.answer_generation_max_tokens,
        ):
            if not delta:
                continue
            parts.append(delta)
            yield {"type": "delta", "delta": delta}

        answer = "".join(parts).strip()
        if not answer:
            # Occasionally Ollama may complete a stream with no token deltas.
            # Retry once through the non-stream endpoint while staying on Gemma.
            answer = self._adapter.complete(
                system_prompt=self._system_prompt(),
                user_prompt=self._user_prompt(question, evidence),
                temperature=settings.answer_generation_temperature,
                max_tokens=settings.answer_generation_max_tokens,
            )
            if not answer:
                answer = "Insufficient evidence."
            yield {"type": "delta", "delta": answer}

        yield {"type": "final", **self._final_payload(answer, source_map)}

    def health_status(self) -> dict[str, object]:
        return self._adapter.health_status()


class QueryUpgradeGenerator:
    def __init__(self, adapter: OllamaChatAdapter) -> None:
        self._adapter = adapter

    def system_prompt_for_debug(self) -> str:
        return self._system_prompt()

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You rewrite user questions into retrieval-optimized search queries for a university-admissions RAG system. "
            "Preserve user intent and concrete constraints exactly. "
            "You may add clarifying keywords that improve retrieval precision (for example: eligibility, deadlines, required documents, fees, portal, process, timeline). "
            "Do not answer the question. Do not invent facts. Do not mention unknown values. "
            "Return exactly one upgraded query as plain text on a single line with no quotes, bullets, or explanations."
        )

    def _user_prompt(self, question: str, domains: list[str]) -> str:
        domain_text = ", ".join(domains) if domains else "(none provided)"
        return "\n".join(
            [
                "User question:",
                question.strip(),
                "",
                "Selected domain filters:",
                domain_text,
                "",
                "Output one upgraded retrieval query.",
            ]
        )

    def upgrade(self, question: str, domains: list[str]) -> str:
        upgraded = self._adapter.complete(
            system_prompt=self._system_prompt(),
            user_prompt=self._user_prompt(question, domains),
            temperature=settings.query_upgrade_temperature,
            max_tokens=settings.query_upgrade_max_tokens,
        )
        sanitized = _sanitize_single_line(upgraded)
        if len(sanitized) < 3:
            raise ValueError("Query upgrader returned an invalid upgraded query")
        return sanitized


def build_answer_generator() -> GroundedAnswerGenerator:
    backend = settings.answer_generation_backend.strip().lower()
    if backend != "ollama":
        raise ValueError(
            "Only ANSWER_GENERATION_BACKEND=ollama is supported in this build to enforce model-generated responses"
        )

    model = settings.answer_generation_model.strip().lower()
    if "gemma" not in model:
        raise ValueError(
            "Only Gemma models are supported in this build. Set ANSWER_GENERATION_MODEL to a Gemma variant."
        )

    adapter = OllamaChatAdapter(
        base_url=settings.answer_generation_base_url,
        model=settings.answer_generation_model,
        timeout_s=settings.answer_generation_timeout_s,
    )
    return GroundedAnswerGenerator(adapter=adapter)


def build_query_upgrader() -> QueryUpgradeGenerator:
    backend = settings.answer_generation_backend.strip().lower()
    if backend != "ollama":
        raise ValueError("Only ANSWER_GENERATION_BACKEND=ollama is supported for query upgrading")

    adapter = OllamaChatAdapter(
        base_url=settings.answer_generation_base_url,
        model=settings.answer_generation_model,
        timeout_s=settings.answer_generation_timeout_s,
    )
    return QueryUpgradeGenerator(adapter=adapter)
