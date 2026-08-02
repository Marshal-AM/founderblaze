#!/usr/bin/env python3
"""Protocol smoke for FounderBlaze Python A2MCP (no vendor calls)."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4021"


def get(path: str) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(BASE + path, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode()
        try:
            return resp.status, json.loads(body)
        except json.JSONDecodeError:
            return resp.status, body


def post(path: str, payload: dict) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method="POST",
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    code, health = get("/health")
    assert code == 200 and health.get("ok") is True, health
    print("health ok")

    code, discovery = get("/v1/discovery")
    assert code == 200, discovery
    assert discovery.get("asp", {}).get("name") == "FounderBlaze", discovery
    names = [s.get("name") for s in discovery.get("services", [])]
    assert names == ["automated-product-demo"], names
    print("discovery ok", names)

    code, created = post(
        "/v1/services/automated-product-demo/jobs",
        {
            "input": {
                "website_url": "https://example.com",
                "script": "Show the homepage briefly.",
            }
        },
    )
    assert code == 202, created
    assert created.get("job_id"), created
    print("create 202", created.get("job_id"), "status=", created.get("status"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
