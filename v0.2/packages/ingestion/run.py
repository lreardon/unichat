"""CLI entry point for full university ingestion.

Usage:
    uv run python -m packages.ingestion.run \
        --university-id <UUID> --domain <domain> \
        [--allowed-subdomains www.example.edu research.example.edu] \
        [--outside-depth 1]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid

from packages.api.dependencies import build_embedder
from packages.core.config import Settings
from packages.core.database import create_engine, create_session_factory
from packages.core.models import University
from packages.core.vector_store.pg_vector_store import PgVectorStore
from packages.ingestion.config import IngestionSettings
from packages.ingestion.pipeline import IngestPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


async def main(
    university_id: uuid.UUID,
    domain: str,
    allowed_subdomains: list[str] | None = None,
    outside_depth: int | None = None,
) -> None:
    settings = Settings()
    ingestion_settings = IngestionSettings()

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    # Update university config with crawl scope if provided
    if allowed_subdomains is not None or outside_depth is not None:
        from sqlalchemy import select

        async with session_factory() as session:
            result = await session.execute(
                select(University).where(University.id == university_id)
            )
            uni = result.scalar_one()
            config = dict(uni.config) if uni.config else {}
            if allowed_subdomains is not None:
                config["allowed_subdomains"] = allowed_subdomains
            if outside_depth is not None:
                config["outside_depth"] = outside_depth
            uni.config = config
            await session.commit()
        logger.info(
            "Updated crawl scope: allowed_subdomains=%s, outside_depth=%s",
            allowed_subdomains,
            outside_depth,
        )

    embedder = build_embedder(settings)
    vector_store = PgVectorStore(
        session_factory=session_factory,
        dimension=settings.embedding_dimension,
    )

    pipeline = IngestPipeline(
        session_factory=session_factory,
        embedder=embedder,
        vector_store=vector_store,
        settings=ingestion_settings,
    )

    logger.info("Starting ingestion for %s (university_id=%s)", domain, university_id)
    report = await pipeline.ingest_university(university_id, domain)

    logger.info("=== Ingestion Report ===")
    logger.info("Pages crawled:       %d", report.pages_crawled)
    logger.info("Pages new/changed:   %d", report.pages_new_or_changed)
    logger.info("Pages unchanged:     %d", report.pages_unchanged)
    logger.info("Chunks created:      %d", report.chunks_created)
    logger.info("Entities extracted:  %d", report.entities_extracted)
    if report.errors:
        logger.warning("Errors (%d):", len(report.errors))
        for err in report.errors[:20]:
            logger.warning("  %s", err)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a university website")
    parser.add_argument("--university-id", type=uuid.UUID, required=True)
    parser.add_argument("--domain", type=str, required=True)
    parser.add_argument(
        "--allowed-subdomains",
        nargs="+",
        default=None,
        help="Whitelist of subdomains to crawl (e.g. www.unsw.edu.au research.unsw.edu.au)",
    )
    parser.add_argument(
        "--outside-depth",
        type=int,
        default=None,
        help="How many link-hops outside whitelisted subdomains to follow (default: 0)",
    )
    args = parser.parse_args()

    asyncio.run(
        main(
            args.university_id,
            args.domain,
            args.allowed_subdomains,
            args.outside_depth,
        )
    )
