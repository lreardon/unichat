"""Uvicorn entry point: `uvicorn packages.api.server:app --reload`."""

from packages.api.app import create_app

app = create_app()
