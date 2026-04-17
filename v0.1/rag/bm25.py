from __future__ import annotations

import math
from collections import Counter

from rag.embedding import HashingEmbeddingProvider


class BM25Index:
    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.avg_doc_len = 0.0
        self.doc_freqs: dict[str, int] = {}
        self.term_freqs: list[dict[str, int]] = []
        self.doc_lengths: list[int] = []

    def build(self, texts: list[str]) -> None:
        tokenized = [HashingEmbeddingProvider.tokenize(text) for text in texts]
        self.doc_lengths = [len(tokens) for tokens in tokenized]
        self.avg_doc_len = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_lengths else 0.0
        self.term_freqs = []
        self.doc_freqs = {}

        for tokens in tokenized:
            counts = Counter(tokens)
            self.term_freqs.append(dict(counts))
            for term in counts.keys():
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

    def idf(self, term: str) -> float:
        n = len(self.term_freqs)
        df = self.doc_freqs.get(term, 0)
        if n == 0:
            return 0.0
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_index: int) -> float:
        if doc_index < 0 or doc_index >= len(self.term_freqs):
            return 0.0

        q_terms = HashingEmbeddingProvider.tokenize(query)
        if not q_terms:
            return 0.0

        tf_doc = self.term_freqs[doc_index]
        dl = self.doc_lengths[doc_index] if self.doc_lengths else 0
        denom_norm = self.k1 * (1.0 - self.b + self.b * (dl / self.avg_doc_len)) if self.avg_doc_len > 0 else self.k1

        score = 0.0
        for term in q_terms:
            tf = tf_doc.get(term, 0)
            if tf <= 0:
                continue
            idf = self.idf(term)
            score += idf * (tf * (self.k1 + 1.0)) / (tf + denom_norm)
        return score
