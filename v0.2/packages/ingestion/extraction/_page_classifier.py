# from __future__ import annotations

# import re

# from packages.ingestion.extraction.models import PageType

# _RULES: list[tuple[re.Pattern[str], PageType]] = [
#     (
#         re.compile(r"/facult|/staff|/people|/professor|/researcher", re.IGNORECASE),
#         PageType.FACULTY,
#     ),
#     (
#         re.compile(r"/program|/degree|/major|/minor|/course|/curriculum", re.IGNORECASE),
#         PageType.PROGRAMS,
#     ),
#     (
#         re.compile(
#             r"/scholar|/financial|/funding|/award|/bursary|/fellowship", re.IGNORECASE
#         ),
#         PageType.SCHOLARSHIPS,
#     ),
#     (
#         re.compile(r"/admiss|/apply|/requirement|/deadline|/enrol", re.IGNORECASE),
#         PageType.ADMISSIONS,
#     ),
# ]


# # def classify_page(url: str) -> PageType:
# #     """Classify a URL into a PageType based on path patterns. First match wins."""
# #     path = urlparse(url).path
# #     for pattern, page_type in _RULES:
# #         if pattern.search(path):
# #             return page_type
# #     return PageType.GENERAL
