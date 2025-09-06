#!/usr/bin/env python3
"""Unified CLI for common Instructify API workflows.

This Typer-based CLI wraps the public API to provide
simple commands for automation and CI.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests  # type: ignore[import-untyped]
import typer  # type: ignore[import-not-found]

from scripts import scorecard

API_URL = os.environ.get("API_URL", "http://localhost:8000")

app = typer.Typer(help="Interact with the Instructify API")


@app.command()
def ingest(project_id: str, path: Path) -> None:
    """Ingest a document for a project via the API."""
    with path.open("rb") as f:
        resp = requests.post(
            f"{API_URL}/ingest", params={"project_id": project_id}, files={"file": f}
        )
    typer.echo(resp.json())


@app.command()
def reparse(doc_id: str) -> None:
    """Trigger re-parsing for an existing document."""
    resp = requests.post(f"{API_URL}/documents/{doc_id}/reparse")
    typer.echo(resp.json())


@app.command()
def export(doc_id: str, fmt: str = typer.Argument("jsonl")) -> None:
    """Export a document in the given format."""
    resp = requests.post(f"{API_URL}/export/{fmt}", json={"doc_ids": [doc_id]})
    typer.echo(resp.json())


release_app = typer.Typer(help="Manage dataset releases")


@release_app.command("create")
def release_create(project_id: str) -> None:
    """Create a new dataset release for a project."""
    resp = requests.post(f"{API_URL}/projects/{project_id}/releases")
    typer.echo(resp.json())


@release_app.command("diff")
def release_diff(base: str, compare: str) -> None:
    """Diff two releases and show changes."""
    resp = requests.get(
        f"{API_URL}/releases/diff", params={"base": base, "compare": compare}
    )
    typer.echo(resp.json())


app.add_typer(release_app, name="release")


@app.command()
def scorecard_cli(
    path: Path = typer.Option(Path("examples/bundles"), "--path")
) -> None:
    """Run scorecard checks on example bundles."""
    ok = scorecard.run(path)
    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":
    app()
