#!/usr/bin/env python3
"""Simple CLI for managing dataset releases via the API."""
import argparse
import json
import os

import requests

API_URL = os.environ.get("API_URL", "http://localhost:8000")


def main() -> None:
    parser = argparse.ArgumentParser(description="Dataset release helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="create a release")
    p_create.add_argument("project_id")

    p_list = sub.add_parser("list", help="list releases for a project")
    p_list.add_argument("project_id")

    p_get = sub.add_parser("get", help="get release details")
    p_get.add_argument("release_id")

    p_diff = sub.add_parser("diff", help="diff two releases")
    p_diff.add_argument("base")
    p_diff.add_argument("compare")

    p_export = sub.add_parser("export", help="export a release")
    p_export.add_argument("release_id")

    args = parser.parse_args()

    if args.cmd == "create":
        resp = requests.post(f"{API_URL}/projects/{args.project_id}/releases")
    elif args.cmd == "list":
        resp = requests.get(f"{API_URL}/projects/{args.project_id}/releases")
    elif args.cmd == "get":
        resp = requests.get(f"{API_URL}/releases/{args.release_id}")
    elif args.cmd == "diff":
        resp = requests.get(
            f"{API_URL}/releases/diff",
            params={"base": args.base, "compare": args.compare},
        )
    elif args.cmd == "export":
        resp = requests.get(f"{API_URL}/releases/{args.release_id}/export")
    else:  # pragma: no cover - argparse ensures cmd
        parser.print_help()
        return

    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
