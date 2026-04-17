from __future__ import annotations

import re

from syntok import segmenter


_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    words = sentence.split()
    if not words:
        return []

    pieces: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        pieces.append(current)
        current = word
    pieces.append(current)
    return pieces


def _split_sentences(text: str, max_chars: int) -> list[str]:
    normalized = _normalize_text(text)
    if not normalized:
        return []

    sentences: list[str] = []
    for paragraph in segmenter.analyze(normalized):
        for sentence_tokens in paragraph:
            sentence = "".join(token.spacing + token.value for token in sentence_tokens).strip()
            if not sentence:
                continue
            if len(sentence) <= max_chars:
                sentences.append(sentence)
            else:
                sentences.extend(_split_long_sentence(sentence, max_chars))
    return sentences


def _chunk_sentences(sentences: list[str], chunk_size: int, overlap: int) -> list[str]:
    if not sentences:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(sentences):
        end = start
        current_len = 0

        while end < len(sentences):
            sentence = sentences[end]
            added_len = len(sentence) + (1 if current_len > 0 else 0)
            if current_len > 0 and (current_len + added_len) > chunk_size:
                break
            current_len += added_len
            end += 1

        if end == start:
            end += 1

        chunks.append(" ".join(sentences[start:end]).strip())

        if end >= len(sentences):
            break

        if overlap <= 0:
            start = end
            continue

        # Slide the next chunk start backwards by sentence boundaries up to overlap chars.
        next_start = end
        carry_len = 0
        while next_start > start:
            sentence = sentences[next_start - 1]
            added_len = len(sentence) + (1 if carry_len > 0 else 0)
            if carry_len + added_len > overlap:
                break
            next_start -= 1
            carry_len += added_len

        start = next_start if next_start > start else end

    return chunks

def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    sentences = _split_sentences(text, chunk_size)
    return _chunk_sentences(sentences, chunk_size, overlap)


def chunk_sections(
    sections: list[tuple[str, str]],
    *,
    chunk_size_chars: int,
    chunk_overlap_chars: int,
) -> list[tuple[str, str]]:
    output: list[tuple[str, str]] = []
    for heading, text in sections:
        for chunk_text in _chunk_text(text, chunk_size_chars, chunk_overlap_chars):
            output.append((heading, chunk_text))
    return output
