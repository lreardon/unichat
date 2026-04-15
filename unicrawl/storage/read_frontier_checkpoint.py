import json
from pathlib import Path

from unicrawl.storage.frontier_checkpoint import FrontierCheckpoint


def read_frontier_checkpoint(base_output_dir: Path, root_url: str) -> tuple[FrontierCheckpoint | None, str | None]:
    checkpoint_path = base_output_dir / "frontier-checkpoint.json"
    if not checkpoint_path.exists():
        return None, None

    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, "corrupt"

    checkpoint_root_url = payload.get("root_url")
    if checkpoint_root_url != root_url:
        return None, "incompatible-root-url"

    queue_payload = payload.get("queue")
    visited_payload = payload.get("visited")
    pages_saved = payload.get("pages_saved")
    pages_skipped = payload.get("pages_skipped")
    errors = payload.get("errors")
    saved_at = payload.get("saved_at")

    if not isinstance(queue_payload, list) or not isinstance(visited_payload, list):
        return None, "corrupt"
    if not isinstance(pages_saved, int) or not isinstance(pages_skipped, int) or not isinstance(errors, int):
        return None, "corrupt"
    if not isinstance(saved_at, str):
        return None, "corrupt"

    queue: list[tuple[str, int]] = []
    for entry in queue_payload:
        if not isinstance(entry, list) or len(entry) != 2:
            return None, "corrupt"
        url, depth = entry
        if not isinstance(url, str) or not isinstance(depth, int):
            return None, "corrupt"
        queue.append((url, depth))

    visited: list[str] = []
    for entry in visited_payload:
        if not isinstance(entry, str):
            return None, "corrupt"
        visited.append(entry)

    return (
        FrontierCheckpoint(
            root_url=checkpoint_root_url,
            queue=queue,
            visited=visited,
            pages_saved=pages_saved,
            pages_skipped=pages_skipped,
            errors=errors,
            saved_at=saved_at,
        ),
        None,
    )
