from __future__ import annotations

import re
from collections import OrderedDict

from rag.types import SearchResult


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_PROCESS_QUERY_RE = re.compile(
    r"\b(step|steps|stage|stages|process|how\s+to\s+apply|application\s+guide|application\s+process|guide)\b",
    re.IGNORECASE,
)
_PROCESS_HEADING_RE = re.compile(r"\b(step|stage|application|process|how to apply|guide)\b", re.IGNORECASE)
_STEP_LINE_RE = re.compile(r"^\s*(?:step\s*\d+|stage\s*\d+|\d+[.)]|[-*])\s*", re.IGNORECASE)


def _extractive_sentence(text: str, question: str) -> str:
    question_terms = {token.lower() for token in re.findall(r"[A-Za-z0-9]+", question)}
    sentences = _SENTENCE_RE.split(text.strip())
    best_sentence = ""
    best_score = -1
    for sentence in sentences:
        tokens = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", sentence)]
        if not tokens:
            continue
        overlap = len([t for t in tokens if t in question_terms])
        score = overlap / len(tokens)
        if score > best_score:
            best_score = score
            best_sentence = sentence.strip()
    return best_sentence or text.strip()[:280]


def _is_process_question(question: str) -> bool:
    return _PROCESS_QUERY_RE.search(question) is not None


def _extract_step_candidates(text: str) -> list[str]:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    steps: list[str] = []

    for line in lines:
        cleaned = _STEP_LINE_RE.sub("", line).strip()
        if len(cleaned) < 24:
            continue
        steps.append(cleaned)

    if steps:
        return steps

    # Fallback: treat substantive sentences as candidate steps.
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(text) if sentence.strip()]
    return [sentence for sentence in sentences if len(sentence) >= 32]


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    deduped: list[SearchResult] = []
    seen: set[tuple[str, str, str]] = set()
    for result in results:
        key = (result.url, result.heading.strip().lower(), result.text[:180].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _filtered_results(results: list[SearchResult]) -> list[SearchResult]:
    ordered = sorted(results, key=lambda item: item.score, reverse=True)
    if not ordered:
        return []

    top_score = ordered[0].score
    floor = max(0.18, top_score * 0.55)
    filtered = [item for item in ordered if item.score >= floor]
    if not filtered:
        filtered = ordered[:2]
    return _dedupe_results(filtered)


def _citation_payload(source: int, result: SearchResult) -> dict[str, object]:
    return {
        "source": source,
        "url": result.url,
        "domain": result.domain,
        "heading": result.heading,
        "score": round(result.score, 4),
        "chunk_id": result.chunk_id,
    }


def _build_process_answer(question: str, results: list[SearchResult]) -> dict[str, object] | None:
    ranked = sorted(
        results,
        key=lambda item: (_PROCESS_HEADING_RE.search(item.heading) is not None, item.score),
        reverse=True,
    )

    lines: list[str] = []
    citations_by_key: OrderedDict[tuple[str, str], tuple[int, SearchResult]] = OrderedDict()
    seen_steps: set[str] = set()

    for result in ranked:
        result_key = (result.url, result.heading)
        if result_key not in citations_by_key:
            citations_by_key[result_key] = (len(citations_by_key) + 1, result)
        source = citations_by_key[result_key][0]

        for candidate in _extract_step_candidates(result.text):
            normalized = re.sub(r"\s+", " ", candidate).strip().lower()
            if normalized in seen_steps:
                continue
            seen_steps.add(normalized)
            lines.append(f"{len(lines) + 1}. {candidate} [source {source}]")
            if len(lines) >= 6:
                break
        if len(lines) >= 6:
            break

    if not lines:
        return None

    citations = [_citation_payload(source, result) for source, result in citations_by_key.values()]
    return {
        "answer": "Based on the selected domain documents, the likely application-guide steps are:\n" + "\n".join(lines),
        "insufficient_evidence": False,
        "citations": citations[:5],
    }


def build_grounded_answer(question: str, results: list[SearchResult]) -> dict[str, object]:
    usable_results = _filtered_results(results)
    if not usable_results:
        return {
            "answer": "I could not find enough evidence in the selected domains to answer that confidently.",
            "insufficient_evidence": True,
            "citations": [],
        }

    if _is_process_question(question):
        process_answer = _build_process_answer(question, usable_results)
        if process_answer is not None:
            return process_answer

    summary_lines: list[str] = []
    citations: list[dict[str, object]] = []
    seen_sentences: set[str] = set()

    for idx, result in enumerate(usable_results[:5], start=1):
        sentence = _extractive_sentence(result.text, question)
        sentence_key = re.sub(r"\s+", " ", sentence).strip().lower()
        if sentence_key in seen_sentences:
            continue
        seen_sentences.add(sentence_key)
        summary_lines.append(f"- {sentence} [source {idx}]")
        citations.append(_citation_payload(idx, result))

    answer = "Based on the selected domain documents, here is what I found:\n" + "\n".join(summary_lines)
    return {
        "answer": answer,
        "insufficient_evidence": False,
        "citations": citations,
    }
