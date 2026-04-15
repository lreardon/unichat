import argparse
import asyncio
import sys
from pathlib import Path

from unicrawl.crawler.run_crawl import run_crawl
from unicrawl.logging.configure_logger import configure_logger
from unicrawl.logging.get_logger import get_logger
from unicrawl.models.crawl_config import CrawlConfig
from unicrawl.normalization.extract_university_name import extract_university_name
from unicrawl.normalization.normalize_url import normalize_url
from unicrawl.storage.write_link_graph import write_link_graph


def _normalize_cli_args(argv: list[str]) -> list[str]:
    if not argv:
        return argv
    if argv[0] in {"crawl", "graph", "-h", "--help"}:
        return argv
    return ["crawl", *argv]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="unicrawl")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl_parser = subparsers.add_parser("crawl", help="Run the crawler")
    crawl_parser.add_argument("root_url")
    crawl_parser.add_argument("--force", action="store_true", help="Bypass robots.txt checks")
    crawl_parser.add_argument(
        "--timing-threshold-ms",
        type=float,
        default=None,
        help="Log timing events only when they exceed this duration in milliseconds",
    )

    graph_parser = subparsers.add_parser("graph", help="Regenerate graph artifacts from persisted crawl data")
    graph_parser.add_argument("root_url")

    return parser


def _run_crawl_command(args: argparse.Namespace) -> None:
    logger = get_logger()

    crawl_config = CrawlConfig(root_url=args.root_url, force=args.force)
    if args.timing_threshold_ms is not None:
        crawl_config.timing_log_threshold_ms = args.timing_threshold_ms

    logger.info(
        "crawl.start root_url={} force={} timing_threshold_ms={}",
        args.root_url,
        args.force,
        crawl_config.timing_log_threshold_ms,
    )
    try:
        result = asyncio.run(run_crawl(crawl_config))
    except KeyboardInterrupt:
        logger.info("crawl.stopped reason=keyboard_interrupt")
        return

    logger.info(
        "crawl.done saved={} skipped={} errors={} output={}",
        result.pages_saved,
        result.pages_skipped,
        result.errors,
        result.output_dir,
    )


def _run_graph_command(args: argparse.Namespace) -> None:
    logger = get_logger()

    root_url = normalize_url(args.root_url)
    if root_url is None:
        raise SystemExit(f"Invalid root URL: {args.root_url}")

    output_dir = Path("universities") / extract_university_name(root_url)
    if not output_dir.exists():
        raise SystemExit(f"No crawl output found for {root_url} at {output_dir}")

    write_link_graph(output_dir, root_url)
    logger.info("graph.done root_url={} output={}", root_url, output_dir)


def main() -> None:
    configure_logger()
    parser = _build_parser()
    args = parser.parse_args(_normalize_cli_args(sys.argv[1:]))

    if args.command == "crawl":
        _run_crawl_command(args)
        return

    if args.command == "graph":
        _run_graph_command(args)
        return

    raise SystemExit(f"Unsupported command: {args.command}")
