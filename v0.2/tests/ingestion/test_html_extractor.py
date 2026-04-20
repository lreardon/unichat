from pathlib import Path

from packages.ingestion.extraction.html_extractor import extract_text, extract_title

FIXTURES = Path(__file__).parent / "fixtures"


class TestHTMLExtractor:
    def test_extract_text_from_general_page(self) -> None:
        html = (FIXTURES / "sample_general.html").read_text()
        text = extract_text(html)
        assert "Example University" in text
        assert "research institution" in text
        # Should not include nav boilerplate
        assert text.count("Home") <= 1  # trafilatura should strip nav

    def test_extract_text_from_programs_page(self) -> None:
        html = (FIXTURES / "sample_programs.html").read_text()
        text = extract_text(html)
        assert "MSc Computer Science" in text or "Computer Science" in text
        assert "120 credits" in text or "2-year" in text

    def test_extract_title(self) -> None:
        html = (FIXTURES / "sample_general.html").read_text()
        title = extract_title(html)
        assert "Example University" in title

    def test_extract_title_from_h1_fallback(self) -> None:
        html = "<html><body><h1>My Page Title</h1><p>content</p></body></html>"
        title = extract_title(html)
        assert "My Page Title" in title

    def test_extract_text_empty_html(self) -> None:
        text = extract_text("<html><body></body></html>")
        assert text == "" or text.strip() == ""

    def test_extract_text_returns_string(self) -> None:
        html = (FIXTURES / "sample_faculty.html").read_text()
        text = extract_text(html)
        assert isinstance(text, str)
        assert len(text) > 0
