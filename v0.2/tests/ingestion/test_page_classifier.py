from packages.ingestion.extraction.models import PageType
from packages.ingestion.extraction._page_classifier import classify_page


class TestPageClassifier:
    def test_faculty_urls(self) -> None:
        assert classify_page("https://example.edu/faculty/chen") == PageType.FACULTY
        assert classify_page("https://example.edu/people/staff") == PageType.FACULTY
        assert classify_page("https://example.edu/department/professors") == PageType.FACULTY
        assert classify_page("https://example.edu/researchers/ai") == PageType.FACULTY

    def test_programs_urls(self) -> None:
        assert classify_page("https://example.edu/programs/msc-cs") == PageType.PROGRAMS
        assert classify_page("https://example.edu/degrees/phd") == PageType.PROGRAMS
        assert classify_page("https://example.edu/courses/fall-2026") == PageType.PROGRAMS

    def test_scholarships_urls(self) -> None:
        url = "https://example.edu/scholarships/international"
        assert classify_page(url) == PageType.SCHOLARSHIPS
        assert classify_page("https://example.edu/financial-aid") == PageType.SCHOLARSHIPS
        assert classify_page("https://example.edu/funding/phd") == PageType.SCHOLARSHIPS

    def test_admissions_urls(self) -> None:
        assert classify_page("https://example.edu/admissions/graduate") == PageType.ADMISSIONS
        assert classify_page("https://example.edu/apply/now") == PageType.ADMISSIONS
        assert classify_page("https://example.edu/requirements/msc") == PageType.ADMISSIONS

    def test_general_urls(self) -> None:
        assert classify_page("https://example.edu/about") == PageType.GENERAL
        assert classify_page("https://example.edu/news/2026") == PageType.GENERAL
        assert classify_page("https://example.edu/") == PageType.GENERAL

    def test_case_insensitive(self) -> None:
        assert classify_page("https://example.edu/Faculty/Chen") == PageType.FACULTY
        assert classify_page("https://example.edu/PROGRAMS/MSC") == PageType.PROGRAMS

    def test_first_match_wins(self) -> None:
        # /faculty/programs → faculty wins since faculty pattern matches first
        assert classify_page("https://example.edu/faculty/programs") == PageType.FACULTY
