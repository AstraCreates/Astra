import imaplib

import pytest

from backend.testing.email_reader import wait_for_verification_code, wait_for_verification_url


class FailingImap:
    def __init__(self, *args, **kwargs):
        pass

    def login(self, email_address, password):
        raise imaplib.IMAP4.error("bad creds")

    def logout(self):
        return None


def test_wait_for_verification_url_raises_on_imap_auth_failure(monkeypatch):
    monkeypatch.setattr("backend.testing.email_reader.imaplib.IMAP4_SSL", FailingImap)

    with pytest.raises(RuntimeError, match="IMAP authentication failed"):
        wait_for_verification_url("test@example.com", "bad-password", "notion", timeout=1, poll_interval=0)


def test_wait_for_verification_code_raises_on_imap_auth_failure(monkeypatch):
    monkeypatch.setattr("backend.testing.email_reader.imaplib.IMAP4_SSL", FailingImap)

    with pytest.raises(RuntimeError, match="IMAP authentication failed"):
        wait_for_verification_code("test@example.com", "bad-password", "notion", timeout=1, poll_interval=0)
