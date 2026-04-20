"""Tests for the structural chunker — the most critical ingestion component."""

from pathlib import Path

from packages.ingestion.chunking.structural_chunker import HTMLStructuralChunker
from packages.ingestion.chunking.token_counter import estimate_tokens
from packages.ingestion.extraction.models import PageType

FIXTURES = Path(__file__).parent / "fixtures"


class TestTablePreservation:
    """Tables must never be split across chunks."""

    def test_table_stays_in_single_chunk(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=50, max_tokens=2000, hard_cap=3000)
        chunks = chunker.chunk(html, PageType.PROGRAMS)

        # Find the chunk with the admission requirements table
        table_chunks = [c for c in chunks if "GPA" in c.text and "IELTS" in c.text]
        assert len(table_chunks) >= 1, "Table content should exist in at least one chunk"

        # GPA and IELTS should be in the same chunk
        for chunk in table_chunks:
            if "GPA" in chunk.text:
                assert "IELTS" in chunk.text or "TOEFL" in chunk.text, \
                    "Table rows should not be split across chunks"


class TestDefinitionListPreservation:
    """Definition lists (<dl>) must never be split."""

    def test_dl_stays_in_single_chunk(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=50, max_tokens=2000, hard_cap=3000)
        chunks = chunker.chunk(html, PageType.PROGRAMS)

        # Find chunk with course definitions
        dl_chunks = [c for c in chunks if "Statistical Learning" in c.text]
        assert len(dl_chunks) >= 1
        # All courses should be in the same chunk
        for chunk in dl_chunks:
            if "Statistical Learning" in chunk.text:
                assert "Data Engineering" in chunk.text, \
                    "DL items should not be split across chunks"


class TestHeadingTrail:
    """Every chunk should have the correct heading trail."""

    def test_heading_trail_present(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=20, max_tokens=500, hard_cap=1200)
        chunks = chunker.chunk(html, PageType.PROGRAMS)

        assert len(chunks) > 0, "Should produce at least one chunk"
        # At least some chunks should have heading trails
        chunks_with_trails = [c for c in chunks if c.heading_trail]
        assert len(chunks_with_trails) > 0, "Some chunks should have heading trails"


class TestTokenBounds:
    """Chunks should respect token boundaries."""

    def test_no_chunk_exceeds_hard_cap(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(
            min_tokens=100, target_tokens=200, max_tokens=400, hard_cap=600
        )
        chunks = chunker.chunk(html, PageType.PROGRAMS)

        for chunk in chunks:
            tokens = estimate_tokens(chunk.text)
            assert tokens <= 600 + 50, \
                f"Chunk exceeds hard cap: {tokens} tokens. Text: {chunk.text[:100]}..."

    def test_produces_multiple_chunks_for_long_content(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(
            min_tokens=20, target_tokens=50, max_tokens=100, hard_cap=200
        )
        chunks = chunker.chunk(html, PageType.PROGRAMS)
        assert len(chunks) > 1, "Long content should produce multiple chunks"


class TestFacultyChunking:
    """Faculty pages: one chunk per profile."""

    def test_one_chunk_per_faculty_profile(self) -> None:
        html = (FIXTURES / "sample_faculty.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=20, max_tokens=2000, hard_cap=3000)
        chunks = chunker.chunk(html, PageType.FACULTY)

        # Should have at least 3 chunks (one per professor)
        assert len(chunks) >= 3, f"Expected >=3 chunks for 3 profiles, got {len(chunks)}"

        # Each professor should appear in exactly one chunk
        alice_chunks = [c for c in chunks if "Alice Chen" in c.text]
        bob_chunks = [c for c in chunks if "Bob Williams" in c.text]
        carol_chunks = [c for c in chunks if "Carol Martinez" in c.text]

        assert len(alice_chunks) == 1, "Alice should be in exactly one chunk"
        assert len(bob_chunks) == 1, "Bob should be in exactly one chunk"
        assert len(carol_chunks) == 1, "Carol should be in exactly one chunk"

    def test_faculty_chunk_contains_full_profile(self) -> None:
        html = (FIXTURES / "sample_faculty.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=20, max_tokens=2000, hard_cap=3000)
        chunks = chunker.chunk(html, PageType.FACULTY)

        alice_chunk = next(c for c in chunks if "Alice Chen" in c.text)
        assert "Machine Learning" in alice_chunk.text
        assert "NLP Lab" in alice_chunk.text


class TestEdgeCases:
    def test_empty_html(self) -> None:
        chunker = HTMLStructuralChunker()
        chunks = chunker.chunk("<html><body></body></html>", PageType.GENERAL)
        assert chunks == []

    def test_plain_text_only(self) -> None:
        html = "<html><body><p>Just a single paragraph of text.</p></body></html>"
        chunker = HTMLStructuralChunker(min_tokens=1, max_tokens=1000, hard_cap=1200)
        chunks = chunker.chunk(html, PageType.GENERAL)
        assert len(chunks) == 1
        assert "single paragraph" in chunks[0].text

    def test_chunk_position_is_sequential(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        chunker = HTMLStructuralChunker(min_tokens=20, max_tokens=200, hard_cap=400)
        chunks = chunker.chunk(html, PageType.PROGRAMS)
        positions = [c.position for c in chunks]
        assert positions == list(range(len(chunks)))
