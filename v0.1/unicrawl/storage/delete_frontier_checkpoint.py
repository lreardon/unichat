from pathlib import Path


def delete_frontier_checkpoint(base_output_dir: Path) -> None:
    checkpoint_path = base_output_dir / "frontier-checkpoint.json"
    if checkpoint_path.exists():
        checkpoint_path.unlink()
