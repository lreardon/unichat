"""Ingestion pipeline orchestrator — crawl → extract ��� chunk → embed → store → entities."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.core.embedding.embedder import Embedder
from packages.core.vector_store.vector_store import VectorStore
from packages.ingestion.chunking.structural_chunker import HTMLStructuralChunker
from packages.ingestion.config import IngestionSettings
from packages.ingestion.crawler.change_detector import ChangeDetector
from packages.ingestion.crawler.crawler import CrawlScope, UniversityCrawler
from packages.ingestion.embedding.batch_embedder import BatchEmbedder
from packages.ingestion.embedding.cache import EmbeddingCache
from packages.ingestion.entities.entity_extractor import EntityExtractor
from packages.ingestion.extraction.html_extractor import extract_title
from packages.ingestion.extraction.models import CrawlResult
# from packages.ingestion.extraction._page_classifier import classify_page
from packages.ingestion.storage.document_store import DocumentStore
from packages.ingestion.storage.raw_html_store import RawHTMLStore

logger = logging.getLogger(__name__)


@dataclass
class IngestReport:
    pages_crawled: int = 0
    pages_new_or_changed: int = 0
    pages_unchanged: int = 0
    chunks_created: int = 0
    entities_extracted: int = 0
    errors: list[str] = field(default_factory=list)


class IngestPipeline:
    """Full ingestion pipeline from crawl to embed."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        vector_store: VectorStore,
        settings: IngestionSettings,
    ) -> None:
        self._session_factory = session_factory
        self._vector_store = vector_store
        self._settings = settings

        self._doc_store = DocumentStore(session_factory)
        self._raw_store = RawHTMLStore(settings.raw_html_base_path)
        self._change_detector = ChangeDetector(session_factory)
        self._chunker = HTMLStructuralChunker(
            min_tokens=settings.chunk_min_tokens,
            target_tokens=settings.chunk_target_tokens,
            max_tokens=settings.chunk_max_tokens,
            hard_cap=settings.chunk_hard_cap,
        )

        cache = EmbeddingCache(session_factory, model_id=embedder.model_id)
        self._batch_embedder = BatchEmbedder(
            embedder=embedder,
            cache=cache,
            batch_size=settings.embed_batch_size,
            max_concurrency=settings.embed_max_concurrency,
            max_retries=settings.embed_max_retries,
        )

        self._entity_extractor: EntityExtractor | None = None
        if settings.entity_extraction_enabled and settings.anthropic_api_key:
            self._entity_extractor = EntityExtractor(
                api_key=settings.anthropic_api_key,
                model=settings.entity_model,
                batch_size=settings.entity_batch_size,
                session_factory=session_factory,
                extractor_version=settings.entity_extractor_version,
            )

    async def _load_crawl_scope(
        self, university_id: uuid.UUID, domain: str
    ) -> CrawlScope:
        """Load crawl scope from university config in DB."""
        from sqlalchemy import select

        from packages.core.models import University

        async with self._session_factory() as session:
            result = await session.execute(
                select(University.config).where(University.id == university_id)
            )
            config = result.scalar_one_or_none() or {}

        return CrawlScope.from_university_config(config, domain)

    async def ingest_university(
        self, university_id: uuid.UUID, domain: str
    ) -> IngestReport:
        """Full pipeline: crawl entire university domain."""
        report = IngestReport()
        scope = await self._load_crawl_scope(university_id, domain)

        logger.info(
            "Crawl scope for %s: allowed_subdomains=%s, outside_depth=%d",
            domain,
            scope.allowed_subdomains or ["(all subdomains)"],
            scope.outside_depth,
        )

        async def process_page(result: CrawlResult) -> None:
            try:
                await self._process_page(university_id, result, report)
            except Exception as e:
                logger.exception("Error processing %s", result.url)
                report.errors.append(f"{result.url}: {e}")

        crawler = UniversityCrawler(
            university_id=university_id,
            domain=domain,
            settings=self._settings,
            scope=scope,
            on_page=process_page,
        )
        
        report.pages_crawled = await crawler.run()

        logger.info(
            "Ingestion complete for %s: %d crawled, %d new/changed, %d chunks, %d entities",
            domain,
            report.pages_crawled,
            report.pages_new_or_changed,
            report.chunks_created,
            report.entities_extracted,
        )
        return report

    async def ingest_url(
        self,
        university_id: uuid.UUID,
        url: str,
        html: str | None = None,
    ) -> tuple[uuid.UUID, IngestReport]:
        """Single-URL pipeline. Optionally provide pre-fetched HTML.

        Returns (document_id, report).
        """
        report = IngestReport()

        if html is None:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                html = resp.text

        result = CrawlResult(
            url=url,
            html=html,
            content_hash=CrawlResult.hash_content(html),
        )
        report.pages_crawled = 1
        doc_id = await self._process_page(university_id, result, report)
        return doc_id, report

    async def _process_page(
        self,
        university_id: uuid.UUID,
        result: CrawlResult,
        report: IngestReport,
    ) -> uuid.UUID:
        """Process a single crawled page through the full pipeline."""
        # Save raw HTML
        raw_path = self._raw_store.save(university_id, result.content_hash, result.html)

        # Classify + extract
        # page_type = classify_page(result.url)
        title = extract_title(result.html)
        logger.info("    title=%s", title[:80] if title else "")

        # Upsert document
        doc_id, is_changed = await self._doc_store.upsert_document(
            university_id=university_id,
            url=result.url,
            title=title,
            content_hash=result.content_hash,
            raw_html_path=raw_path,
            # page_type=None,  # page_type,
        )

        if not is_changed:
            report.pages_unchanged += 1
            logger.info("    unchanged (hash match), skipping chunk/embed")
            return doc_id

        report.pages_new_or_changed += 1

        # Delete old chunks for this document
        deleted = await self._vector_store.delete_by_document(document_id=doc_id)
        if deleted:
            logger.info("    replaced %d old chunks", deleted)

        # Chunk
        chunks = self._chunker.chunk(
            result.html,
            None,
            metadata={
                "source_url": result.url,
                "page_type": None,
                "title": title,
            },
        )

        if not chunks:
            logger.info("    no chunks produced (empty content)")
            return doc_id

        logger.info("    chunked → %d chunks", len(chunks))

        # Embed
        embeddings = await self._batch_embedder.embed_chunks(chunks)
        logger.info("    embedded %d chunks", len(embeddings))

        # Store chunks via VectorStore
        chunk_ids: list[uuid.UUID] = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk_id = uuid.uuid4()
            chunk_ids.append(chunk_id)
            await self._vector_store.upsert(
                chunk_id=chunk_id,
                document_id=doc_id,
                university_id=university_id,
                content=chunk.text,
                embedding=embedding,
                position=chunk.position,
                heading_trail=chunk.heading_trail,
                metadata=chunk.metadata,
            )
        report.chunks_created += len(chunks)
        logger.info("    stored %d chunks", len(chunks))

        # Entity extraction
        if self._entity_extractor and chunks:
            logger.info("    extracting entities from %d chunks...", len(chunks))
            chunk_texts = [
                (cid, c.text) for cid, c in zip(chunk_ids, chunks, strict=True)
            ]
            entities_count = await self._entity_extractor.extract_from_chunks(
                chunk_texts, university_id, doc_id
            )
            report.entities_extracted += entities_count
            if entities_count:
                logger.info("    extracted %d entities", entities_count)

        return doc_id
