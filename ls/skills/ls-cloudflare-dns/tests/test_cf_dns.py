from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cf_dns.py"
SPEC = importlib.util.spec_from_file_location("cf_dns", SCRIPT)
cf_dns = importlib.util.module_from_spec(SPEC)
sys.modules["cf_dns"] = cf_dns
assert SPEC and SPEC.loader
SPEC.loader.exec_module(cf_dns)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._json_error = payload is None and text is not None
        self._payload = payload if payload is not None else {"success": True, "errors": [], "messages": [], "result": {}}
        self.headers = headers or {}
        self.text = json.dumps(self._payload) if text is None else text
        self.ok = 200 <= status_code < 400

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response queued")
        return self.responses.pop(0)


class FailingSession:
    def request(self, method, url, **kwargs):
        raise cf_dns.requests.Timeout("boom secret-token")


def envelope(result, **extra):
    return {"success": True, "errors": [], "messages": [], "result": result, **extra}


def test_redacts_tokens_and_authorization(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret-token")
    payload = {
        "Authorization": "Bearer secret-token",
        "message": "secret-token should not appear",
        "nested": {"token": "secret-token"},
    }

    redacted = cf_dns.redact(payload)

    assert redacted["Authorization"] == "<redacted>"
    assert redacted["message"] == "<redacted> should not appear"
    assert redacted["nested"]["token"] == "<redacted>"


def test_pagination_and_rate_limit(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    session = FakeSession(
        [
            FakeResponse(payload=envelope([{"id": "1"}], result_info={"page": 1, "total_pages": 2}), headers={"Ratelimit": '"default";r=1;t=1'}),
            FakeResponse(payload=envelope([{"id": "2"}], result_info={"page": 2, "total_pages": 2}), headers={"retry-after": "3"}),
        ]
    )
    client = cf_dns.CloudflareClient("https://mock.invalid", session=session, retries=0)

    results, info, rate = client.paged("/zones")

    assert results == [{"id": "1"}, {"id": "2"}]
    assert info["total_pages"] == 2
    assert rate == {"retry-after": "3"}
    assert session.calls[0]["params"]["page"] == 1
    assert session.calls[1]["params"]["page"] == 2


def test_zone_ambiguity_returns_candidates(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    session = FakeSession(
        [
            FakeResponse(payload=envelope([], result_info={"total_pages": 1})),
            FakeResponse(payload=envelope([{"id": "z1", "name": "example.com"}, {"id": "z2", "name": "example.com"}], result_info={"total_pages": 1})),
        ]
    )
    client = cf_dns.CloudflareClient("https://mock.invalid", session=session, retries=0)

    with pytest.raises(cf_dns.CliError) as exc:
        cf_dns.resolve_zone(client, "example.com")

    assert exc.value.exit_code == cf_dns.EXIT_AMBIGUOUS_ZONE
    assert len(exc.value.details["candidates"]) == 2


def test_plan_hash_is_canonical_and_stable():
    class Args:
        require_snapshot = False
        snapshot_waiver = False

    first = cf_dns.dry_run_plan("records delete", "/zones/z/dns_records/r", "DELETE", None, Args(), {"id": "r"})
    second = cf_dns.dry_run_plan("records delete", "/zones/z/dns_records/r", "DELETE", None, Args(), {"id": "r"})

    assert first["plan_hash"] == second["plan_hash"]
    assert len(first["plan_hash"]) == 64


def test_delete_apply_requires_confirmation_and_plan_hash(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    session = FakeSession(
        [
            FakeResponse(payload=envelope({"id": "zone123", "name": "example.com"})),
            FakeResponse(payload=envelope({"id": "record123", "name": "www.example.com", "type": "A", "content": "192.0.2.10"})),
        ]
    )
    args = cf_dns.build_parser().parse_args(
        [
            "--api-base",
            "https://mock.invalid",
            "records",
            "delete",
            "0123456789abcdef",
            "record123",
            "--apply",
            "--confirm",
            "yes",
        ]
    )

    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        with pytest.raises(cf_dns.CliError) as exc:
            cf_dns.cmd_records_delete(args)
    finally:
        cf_dns.CloudflareClient = original

    assert exc.value.exit_code == cf_dns.EXIT_CONFIRMATION
    assert "confirm delete" in str(exc.value)


def test_batch_apply_requires_apply_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"deletes": [{"id": "record123"}]}), encoding="utf-8")
    session = FakeSession([FakeResponse(payload=envelope({"id": "0123456789abcdef", "name": "example.com"}))])
    args = cf_dns.build_parser().parse_args(["records", "batch-apply", "0123456789abcdef", "--json", str(batch)])

    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        with pytest.raises(cf_dns.CliError) as exc:
            cf_dns.cmd_records_batch_apply(args)
    finally:
        cf_dns.CloudflareClient = original

    assert exc.value.exit_code == cf_dns.EXIT_CONFIRMATION
    assert "--apply" in str(exc.value)
    assert session.calls == []


def test_normalize_preserves_unknown_fields():
    record = {
        "id": "record123",
        "name": "www.example.com",
        "type": "A",
        "content": "192.0.2.10",
        "ttl": 1,
        "future_field": {"kept": True},
    }

    normalized = cf_dns.normalize_record(record, {"id": "zone123", "name": "example.com"})

    assert normalized["provider_fields"] == {"future_field": {"kept": True}}
    assert normalized["zone_id"] == "zone123"
    assert len(normalized["record_hash"]) == 64


def test_retry_on_rate_limit(monkeypatch):
    monkeypatch.setattr(cf_dns.time, "sleep", lambda _: None)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    session = FakeSession(
        [
            FakeResponse(status_code=429, payload={"success": False, "errors": [{"message": "rate limited"}], "result": None}, headers={"retry-after": "1"}),
            FakeResponse(payload=envelope({"id": "ok"}), headers={"Ratelimit-Policy": '"default";q=1200;w=300'}),
        ]
    )
    client = cf_dns.CloudflareClient("https://mock.invalid", session=session, retries=1)

    response = client.request("GET", "/user/tokens/verify")

    assert response.envelope["result"] == {"id": "ok"}
    assert len(session.calls) == 2
    assert response.rate_limit == {"Ratelimit-Policy": '"default";q=1200;w=300'}


def test_batch_plan_hash_can_be_used_for_batch_apply(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps({"deletes": [{"id": "record123"}]}), encoding="utf-8")
    zone = {"id": "0123456789abcdef", "name": "example.com"}
    session = FakeSession(
        [
            FakeResponse(payload=envelope(zone)),
            FakeResponse(payload=envelope(zone)),
            FakeResponse(payload=envelope({"applied": True})),
        ]
    )
    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        plan_args = cf_dns.build_parser().parse_args(["records", "batch-plan", "0123456789abcdef", "--json", str(batch)])
        plan_payload = cf_dns.cmd_records_batch_plan(plan_args)
        plan_hash = plan_payload["result"]["plan"]["plan_hash"]
        apply_args = cf_dns.build_parser().parse_args(
            [
                "records",
                "batch-apply",
                "0123456789abcdef",
                "--json",
                str(batch),
                "--apply",
                "--confirm",
                "confirm apply",
                "--plan-hash",
                plan_hash,
            ]
        )
        apply_payload = cf_dns.cmd_records_batch_apply(apply_args)
    finally:
        cf_dns.CloudflareClient = original

    assert apply_payload["ok"] is True
    assert apply_payload["plan_hash"] == plan_hash
    assert session.calls[-1]["method"] == "POST"
    assert session.calls[-1]["url"].endswith("/zones/0123456789abcdef/dns_records/batch")


def test_scan_list_uses_review_endpoint(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    zone = {"id": "0123456789abcdef", "name": "example.com"}
    session = FakeSession([FakeResponse(payload=envelope(zone)), FakeResponse(payload=envelope([{"name": "found"}]))])
    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        args = cf_dns.build_parser().parse_args(["records", "scan", "list", "0123456789abcdef"])
        payload = cf_dns.cmd_scan(args, "list")
    finally:
        cf_dns.CloudflareClient = original

    assert payload["result"] == [{"name": "found"}]
    assert session.calls[-1]["method"] == "GET"
    assert session.calls[-1]["url"].endswith("/zones/0123456789abcdef/dns_records/scan/review")


def test_scan_review_dry_run_does_not_post(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    review = tmp_path / "review.json"
    review.write_text(json.dumps({"accepts": [{"name": "www.example.com"}]}), encoding="utf-8")
    zone = {"id": "0123456789abcdef", "name": "example.com"}
    session = FakeSession([FakeResponse(payload=envelope(zone))])
    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        args = cf_dns.build_parser().parse_args(["records", "scan", "review", "0123456789abcdef", "--json", str(review)])
        payload = cf_dns.cmd_scan(args, "review")
    finally:
        cf_dns.CloudflareClient = original

    assert payload["result"]["dry_run"] is True
    assert payload["result"]["plan"]["method"] == "POST"
    assert len(session.calls) == 1


def test_request_exception_is_deterministic_json_error(monkeypatch, capsys):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "secret-token")
    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=FailingSession(), retries=0)
    try:
        exit_code = cf_dns.main(["auth", "verify"])
    finally:
        cf_dns.CloudflareClient = original

    output = json.loads(capsys.readouterr().out)
    assert exit_code == cf_dns.EXIT_API
    assert output["ok"] is False
    assert "secret-token" not in json.dumps(output)
    assert output["errors"][0]["message"] == "Cloudflare API request could not be completed."


def test_bad_json_file_is_deterministic_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not-json", encoding="utf-8")

    with pytest.raises(cf_dns.CliError) as exc:
        cf_dns.read_json_file(str(bad))

    assert exc.value.exit_code == 2
    assert "could not be parsed" in str(exc.value)


def test_import_missing_file_is_deterministic_json_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    missing = tmp_path / "missing-zonefile.txt"
    zone = {"id": "0123456789abcdef", "name": "example.com"}
    session = FakeSession([FakeResponse(payload=envelope(zone))])
    original = cf_dns.CloudflareClient
    cf_dns.CloudflareClient = lambda *a, **kw: original("https://mock.invalid", session=session, retries=0)
    try:
        exit_code = cf_dns.main(["records", "import", "0123456789abcdef", "--file", str(missing)])
    finally:
        cf_dns.CloudflareClient = original

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert output["ok"] is False
    assert output["errors"][0]["message"] == "Text input could not be read."
    assert "Traceback" not in json.dumps(output)


def test_malformed_api_json_becomes_api_error(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    session = FakeSession([FakeResponse(payload=None, text="<html>nope</html>")])
    client = cf_dns.CloudflareClient("https://mock.invalid", session=session, retries=0)

    with pytest.raises(cf_dns.CliError) as exc:
        client.request("GET", "/user/tokens/verify")

    assert exc.value.exit_code == cf_dns.EXIT_API
    assert exc.value.details["errors"][0]["message"] == "Cloudflare API response was not valid JSON."


def test_cli_help_runs_without_token(capsys):
    with pytest.raises(SystemExit) as exc:
        cf_dns.build_parser().parse_args(["records", "--help"])

    assert exc.value.code == 0
    assert "DNS record operations" in capsys.readouterr().out
