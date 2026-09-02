from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts import mail_protocol_imap, mail_protocol_support
from scripts.mail_protocol_imap import ImapAdapter
from scripts.mail_protocol_support import MailControlError, SmtpAdapter
from scripts.mail_types import AccountConfig

_CREDS = {"username": "user", "password": "password"}


def _account(
    *, smtp_tls_mode: str = "starttls", imap_tls: bool = True
) -> AccountConfig:
    return AccountConfig(
        account_id="acct",
        smtp_host="smtp.example.test",
        smtp_tls_mode=smtp_tls_mode,
        imap_host="imap.example.test",
        imap_tls=imap_tls,
    )


def test_imap_rejects_non_tls_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_constructor(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("IMAP client construction must not occur")

    monkeypatch.setattr(mail_protocol_imap.imaplib, "IMAP4_SSL", fail_constructor)

    with pytest.raises(MailControlError) as excinfo:
        ImapAdapter()._connect(_account(imap_tls=False), _CREDS)

    assert excinfo.value.code == "TLS_REQUIRED"


@pytest.mark.parametrize("method", ["verify", "send"])
def test_smtp_rejects_non_tls_before_client_construction(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    def fail_constructor(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("SMTP client construction must not occur")

    monkeypatch.setattr(mail_protocol_support.smtplib, "SMTP", fail_constructor)
    monkeypatch.setattr(mail_protocol_support.smtplib, "SMTP_SSL", fail_constructor)
    adapter = SmtpAdapter()

    with pytest.raises(MailControlError) as excinfo:
        if method == "verify":
            adapter.verify_connectivity(_account(smtp_tls_mode="plain"), _CREDS)
        else:
            adapter._send_prebuilt(
                _account(smtp_tls_mode="plain"), _CREDS, EmailMessage()
            )

    assert excinfo.value.code == "TLS_REQUIRED"


class _FakeSmtp:
    def __init__(self) -> None:
        self.esmtp_features: dict[str, str] = {}
        self.starttls_calls = 0
        self.login_calls = 0

    def __enter__(self) -> _FakeSmtp:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def ehlo(self) -> tuple[int, bytes]:
        return 250, b"ok"

    def starttls(self, **_kwargs: object) -> tuple[int, bytes]:
        self.starttls_calls += 1
        return 220, b"ready"

    def login(self, _username: str, _password: str) -> tuple[int, bytes]:
        self.login_calls += 1
        return 235, b"ok"


def test_smtp_secure_modes_use_tls_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    starttls_client = _FakeSmtp()
    ssl_client = _FakeSmtp()
    constructors: list[str] = []

    def smtp_constructor(*_args: object, **_kwargs: object) -> _FakeSmtp:
        constructors.append("smtp")
        return starttls_client

    def ssl_constructor(*_args: object, **_kwargs: object) -> _FakeSmtp:
        constructors.append("ssl")
        return ssl_client

    monkeypatch.setattr(mail_protocol_support.smtplib, "SMTP", smtp_constructor)
    monkeypatch.setattr(mail_protocol_support.smtplib, "SMTP_SSL", ssl_constructor)
    adapter = SmtpAdapter()

    assert adapter.verify_connectivity(_account(), _CREDS)["mode"] == "starttls"
    assert adapter.verify_connectivity(_account(smtp_tls_mode="ssl"), _CREDS)["mode"] == "ssl"
    assert constructors == ["smtp", "ssl"]
    assert starttls_client.starttls_calls == 1
    assert starttls_client.login_calls == 1
    assert ssl_client.login_calls == 1


class _FakeImap:
    def __init__(self, capabilities: tuple[bytes, ...], expunge_status: str = "OK") -> None:
        self.capabilities = capabilities
        self.expunge_status = expunge_status
        self.uid_calls: list[tuple[object, ...]] = []

    def __enter__(self) -> _FakeImap:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def login(self, _username: str, _password: str) -> tuple[str, list[object]]:
        return "OK", []

    def select(self, _mailbox: str, readonly: bool = False) -> tuple[str, list[object]]:
        del readonly
        return "OK", []

    def uid(self, command: str, *args: object) -> tuple[str, list[object]]:
        self.uid_calls.append((command, *args))
        if command == "EXPUNGE":
            return self.expunge_status, []
        return "OK", []

    def expunge(self) -> tuple[str, list[object]]:
        raise AssertionError("MOVE fallback must not use mailbox-wide EXPUNGE")


def _move_payload() -> dict[str, object]:
    return {
        "mutate_action": "move_messages",
        "mailbox": "INBOX",
        "uids": ["1", "2"],
        "target_mailbox": "Archive",
    }


def test_move_fallback_uses_uid_expunge_for_selected_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeImap((b"IMAP4REV1", b"UIDPLUS"))
    monkeypatch.setattr(
        mail_protocol_imap.imaplib, "IMAP4_SSL", lambda *_args, **_kwargs: client
    )

    result = ImapAdapter().mutate(_account(), _CREDS, _move_payload())

    assert result == {"moved": 2, "target": "Archive"}
    assert [call[0] for call in client.uid_calls] == ["COPY", "STORE", "EXPUNGE"]
    assert client.uid_calls[-1] == ("EXPUNGE", "1,2")


@pytest.mark.parametrize(
    ("capabilities", "expunge_status"),
    [((b"IMAP4REV1",), "OK"), ((b"IMAP4REV1", b"UIDPLUS"), "NO")],
)
def test_move_fallback_never_uses_mailbox_wide_expunge(
    monkeypatch: pytest.MonkeyPatch,
    capabilities: tuple[bytes, ...],
    expunge_status: str,
) -> None:
    client = _FakeImap(capabilities, expunge_status)
    monkeypatch.setattr(
        mail_protocol_imap.imaplib, "IMAP4_SSL", lambda *_args, **_kwargs: client
    )

    with pytest.raises(MailControlError) as excinfo:
        ImapAdapter().mutate(_account(), _CREDS, _move_payload())

    assert excinfo.value.code == "IMAP_MOVE_INCOMPLETE"
    commands = [call[0] for call in client.uid_calls]
    if b"UIDPLUS" in capabilities:
        assert commands == ["COPY", "STORE", "EXPUNGE"]
        assert client.uid_calls[-1] == ("EXPUNGE", "1,2")
    else:
        assert commands == ["COPY", "STORE"]
