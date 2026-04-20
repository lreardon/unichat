"""Structural HTML chunker — heading-aware splitting that preserves tables and profiles.

Rules from the plan:
- Never split a table across chunks
- Never split a definition list (<dl>)
- Heading hierarchy (h1-h3) as primary split boundaries
- Target 400-800 tokens per chunk, hard cap 1200
- Heading trail prefix on every chunk
- Faculty page type: one chunk per profile section
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from packages.ingestion.chunking.token_counter import estimate_tokens
from packages.ingestion.extraction.models import ExtractedChunk, PageType

HEADING_TAGS = {"h1", "h2", "h3"}
BLOCK_TAGS = {"p", "div", "section", "article", "blockquote", "ul", "ol", "li", "pre"}
ATOMIC_TAGS = {"table", "dl"}
FACULTY_MARKERS = {"faculty-profile", "staff-profile", "people-profile", "profile"}


@dataclass
class _Section:
    """Accumulator for a heading-scoped section."""

    heading_trail: list[str] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    token_count: int = 0

    def add(self, text: str) -> None:
        tokens = estimate_tokens(text)
        self.parts.append(text)
        self.token_count += tokens

    @property
    def text(self) -> str:
        return "\n\n".join(p for p in self.parts if p.strip())


class HTMLStructuralChunker:
    """Chunk HTML by structural boundaries."""

    def __init__(
        self,
        *,
        min_tokens: int = 400,
        target_tokens: int = 600,
        max_tokens: int = 800,
        hard_cap: int = 1200,
    ) -> None:
        self._min = min_tokens
        self._target = target_tokens
        self._max = max_tokens
        self._hard_cap = hard_cap

    def chunk(
        self,
        html: str,
        page_type: PageType,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[ExtractedChunk]:
        """Parse HTML and produce chunks respecting structural boundaries."""
        soup = BeautifulSoup(html, "lxml")
        body = soup.body or soup

        if page_type == PageType.FACULTY:
            chunks = self._chunk_faculty(body)
        else:
            sections = self._walk_sections(body)
            chunks = self._merge_sections(sections)

        base_meta = metadata or {}
        result: list[ExtractedChunk] = []
        for i, chunk in enumerate(chunks):
            text = chunk.text.strip()
            if not text:
                continue
            token_count = estimate_tokens(text)
            result.append(
                ExtractedChunk(
                    text=text,
                    position=i,
                    heading_trail=list(chunk.heading_trail),
                    metadata=dict(base_meta),
                    token_count=token_count,
                )
            )
        return result

    def _walk_sections(self, root: Tag) -> list[_Section]:
        """Walk DOM, splitting on headings. Tables and dls are kept atomic."""
        sections: list[_Section] = []
        current_trail: list[str] = []
        current = _Section()

        for element in root.descendants:
            if isinstance(element, NavigableString):
                if not isinstance(element, Tag):
                    text = element.strip()
                    if text and not _is_inside_atomic(element):
                        current.add(text)
                continue

            tag_name = element.name

            if tag_name in HEADING_TAGS:
                heading_text = element.get_text(strip=True)
                if not heading_text:
                    continue

                if current.parts:
                    current.heading_trail = list(current_trail)
                    sections.append(current)
                    current = _Section()

                level = int(tag_name[1])
                current_trail = current_trail[: level - 1]
                current_trail.append(heading_text)
                continue

            if tag_name in ATOMIC_TAGS:
                text = _extract_atomic_text(element)
                if text:
                    current.add(text)
                continue

        if current.parts:
            current.heading_trail = list(current_trail)
            sections.append(current)

        return sections

    def _chunk_faculty(self, root: Tag) -> list[_Section]:
        """Faculty page: one chunk per profile section."""
        sections: list[_Section] = []
        page_heading: list[str] = []

        # Try to find profile containers by class
        profiles = root.find_all(
            lambda tag: tag.name in ("div", "section", "article")
            and _has_profile_class(tag)
        )

        if profiles:
            for profile in profiles:
                section = _Section()
                name = _extract_profile_name(profile)
                section.heading_trail = list(page_heading) + ([name] if name else [])
                section.add(profile.get_text(separator="\n", strip=True))
                sections.append(section)
            return sections

        # Fallback: split on h2/h3 headings (each person gets a heading)
        return self._walk_sections(root)

    def _merge_sections(self, sections: list[_Section]) -> list[_Section]:
        """Merge small sections, split large ones."""
        result: list[_Section] = []

        for section in sections:
            if section.token_count > self._hard_cap:
                result.extend(self._split_section(section))
            elif section.token_count < self._min and result:
                last = result[-1]
                merged_tokens = last.token_count + section.token_count
                if merged_tokens <= self._max:
                    for part in section.parts:
                        last.add(part)
                    continue
                else:
                    result.append(section)
            else:
                result.append(section)

        return result

    def _split_section(self, section: _Section) -> list[_Section]:
        """Split an oversized section on paragraph boundaries."""
        chunks: list[_Section] = []
        current = _Section(heading_trail=list(section.heading_trail))

        for part in section.parts:
            part_tokens = estimate_tokens(part)

            if current.token_count + part_tokens <= self._max:
                current.add(part)
                continue

            if current.parts:
                chunks.append(current)
                current = _Section(heading_trail=list(section.heading_trail))

            if part_tokens <= self._hard_cap:
                current.add(part)
            else:
                # Split on sentence boundaries
                for sub in _split_text_by_sentences(part, self._hard_cap):
                    sub_section = _Section(heading_trail=list(section.heading_trail))
                    sub_section.add(sub)
                    chunks.append(sub_section)

        if current.parts:
            chunks.append(current)

        return chunks


def _is_inside_atomic(element: NavigableString) -> bool:
    """Check if a text node is inside a table or dl (handled separately)."""
    for parent in element.parents:
        if isinstance(parent, Tag) and parent.name in ATOMIC_TAGS:
            return True
    return False


def _extract_atomic_text(element: Tag) -> str:
    """Extract text from a table or dl, preserving row/item structure."""
    if element.name == "table":
        rows: list[str] = []
        for tr in element.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            rows.append(" | ".join(cells))
        return "\n".join(rows)

    if element.name == "dl":
        items: list[str] = []
        for dt in element.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            dd_text = dd.get_text(strip=True) if dd else ""
            items.append(f"{dt.get_text(strip=True)}: {dd_text}")
        return "\n".join(items)

    return element.get_text(separator="\n", strip=True)


def _has_profile_class(tag: Tag) -> bool:
    """Check if a tag has a CSS class suggesting it's a profile card."""
    classes = tag.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    return any(
        any(marker in cls.lower() for marker in FACULTY_MARKERS)
        for cls in classes
    )


def _extract_profile_name(profile: Tag) -> str:
    """Extract the person's name from a profile element."""
    for heading in profile.find_all(HEADING_TAGS):
        name = heading.get_text(strip=True)
        if name:
            return name
    return ""


def _split_text_by_sentences(text: str, max_tokens: int) -> list[str]:
    """Split text into chunks at sentence boundaries, respecting max_tokens."""
    sentences = text.replace(". ", ".\n").split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        tokens = estimate_tokens(sentence)
        if current_tokens + tokens > max_tokens and current:
            chunks.append(" ".join(current))
            current = []
            current_tokens = 0
        current.append(sentence)
        current_tokens += tokens

    if current:
        chunks.append(" ".join(current))

    return chunks
