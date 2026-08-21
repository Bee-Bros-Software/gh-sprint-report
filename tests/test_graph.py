"""Tests for :mod:`sprint_report.graph` and upload wiring in the CLI.

The HTTP layer is stubbed throughout; no network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sprint_report.graph import (
    GraphError,
    GraphUploader,
)


class _Resp:
    """Minimal stand-in for a :class:`requests.Response`."""

    def __init__(self, payload: dict, status_code: int = 200, headers=None) -> None:
        """Store canned response data.

        Args:
            payload: Body returned by :meth:`json`.
            status_code: HTTP status to report.
            headers: Optional response headers.
        """
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.content = self.text.encode()
        self.headers = headers or {}

    def json(self) -> dict:
        """Return the canned payload.

        Returns:
            The payload supplied at construction.
        """
        return self._payload


@pytest.fixture()
def uploader() -> GraphUploader:
    """A uploader with a pre-seeded token so auth is not re-exercised."""
    instance = GraphUploader("tenant", "client", "secret")
    instance._token = "cached-token"
    instance._token_expires_at = 9_999_999_999.0
    return instance


class TestCredentials:
    """Constructor validation and token handling."""

    @pytest.mark.parametrize(
        "args",
        [("", "c", "s"), ("t", "", "s"), ("t", "c", "")],
    )
    def test_missing_credential_rejected(self, args):
        """Every credential is mandatory."""
        with pytest.raises(ValueError):
            GraphUploader(*args)

    def test_token_is_cached(self, monkeypatch):
        """A second call reuses the cached token rather than re-authenticating."""
        instance = GraphUploader("t", "c", "s")
        calls = []

        def _post(*a, **k):
            calls.append(1)
            return _Resp({"access_token": "abc", "expires_in": 3600})

        monkeypatch.setattr(instance._session, "post", _post)
        assert instance._access_token() == "abc"
        assert instance._access_token() == "abc"
        assert len(calls) == 1

    def test_token_failure_raises(self, monkeypatch):
        """Bad credentials surface as a :class:`GraphError`."""
        instance = GraphUploader("t", "c", "s")
        monkeypatch.setattr(
            instance._session,
            "post",
            lambda *a, **k: _Resp({"error": "invalid_client"}, 401),
        )
        with pytest.raises(GraphError, match="Token request failed"):
            instance._access_token()

    def test_token_without_access_token_raises(self, monkeypatch):
        """A 200 with no token is still a failure."""
        instance = GraphUploader("t", "c", "s")
        monkeypatch.setattr(
            instance._session, "post", lambda *a, **k: _Resp({})
        )
        with pytest.raises(GraphError, match="no access_token"):
            instance._access_token()


class TestResolution:
    """Site and drive lookup."""

    def test_resolve_site_drive(self, uploader, monkeypatch):
        """A site path resolves through to its default document library."""
        responses = iter([_Resp({"id": "site-1"}), _Resp({"id": "drive-1"})])
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: next(responses)
        )
        assert uploader.resolve_site_drive("host", "/sites/Eng") == "drive-1"

    def test_site_path_normalised(self, uploader, monkeypatch):
        """A path without a leading slash is accepted."""
        seen = []

        def _request(method, url, **k):
            seen.append(url)
            return _Resp({"id": "x"})

        monkeypatch.setattr(uploader._session, "request", _request)
        uploader.resolve_site_drive("host", "sites/Eng")
        assert "host:/sites/Eng" in seen[0]

    def test_missing_site_raises(self, uploader, monkeypatch):
        """An empty site response is an error, not a silent skip."""
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: _Resp({})
        )
        with pytest.raises(GraphError, match="No site found"):
            uploader.resolve_site_drive("host", "/sites/Nope")

    def test_resolve_user_drive(self, uploader, monkeypatch):
        """A UPN resolves to that user's OneDrive."""
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: _Resp({"id": "od-1"})
        )
        assert uploader.resolve_user_drive("phil@x.com") == "od-1"

    def test_missing_user_drive_raises(self, uploader, monkeypatch):
        """A user with no OneDrive is reported clearly."""
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: _Resp({})
        )
        with pytest.raises(GraphError, match="No OneDrive"):
            uploader.resolve_user_drive("phil@x.com")


class TestUpload:
    """File upload behaviour."""

    def test_uploads_and_returns_url(self, uploader, monkeypatch, tmp_path: Path):
        """A successful upload returns the item's web URL."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"content")
        monkeypatch.setattr(
            uploader._session,
            "request",
            lambda *a, **k: _Resp({"webUrl": "https://sp/deck.pptx"}),
        )
        assert uploader.upload("d1", "Reviews", deck) == "https://sp/deck.pptx"

    def test_builds_nested_path(self, uploader, monkeypatch, tmp_path: Path):
        """The folder and filename are joined into the content path."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        seen = []

        def _request(method, url, **k):
            seen.append(url)
            return _Resp({"webUrl": "u"})

        monkeypatch.setattr(uploader._session, "request", _request)
        uploader.upload("d1", "/Sprint Reviews/", deck, "Sprint 14 Review.pptx")
        assert "root:/Sprint Reviews/Sprint 14 Review.pptx:/content" in seen[0]

    def test_root_upload_omits_folder(self, uploader, monkeypatch, tmp_path: Path):
        """An empty folder uploads to the drive root."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        seen = []
        monkeypatch.setattr(
            uploader._session,
            "request",
            lambda method, url, **k: (seen.append(url), _Resp({"webUrl": "u"}))[1],
        )
        uploader.upload("d1", "", deck)
        assert "root:/deck.pptx:/content" in seen[0]

    def test_missing_file_raises(self, uploader, tmp_path: Path):
        """Uploading a nonexistent path fails before any network call."""
        with pytest.raises(FileNotFoundError):
            uploader.upload("d1", "Reviews", tmp_path / "absent.pptx")

    def test_oversized_file_rejected(self, uploader, tmp_path: Path, monkeypatch):
        """Files past the simple-upload limit are refused with an explanation."""
        deck = tmp_path / "big.pptx"
        deck.write_bytes(b"0" * 16)
        monkeypatch.setattr(
            "sprint_report.graph.SIMPLE_UPLOAD_LIMIT", 8
        )
        with pytest.raises(GraphError, match="simple upload limit"):
            uploader.upload("d1", "Reviews", deck)

    def test_permission_error_surfaces(self, uploader, monkeypatch, tmp_path: Path):
        """A 403 reports the Graph message rather than retrying forever."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        monkeypatch.setattr(
            uploader._session,
            "request",
            lambda *a, **k: _Resp({"error": {"code": "accessDenied"}}, 403),
        )
        with pytest.raises(GraphError, match="403"):
            uploader.upload("d1", "Reviews", deck)

    def test_throttling_is_retried(self, uploader, monkeypatch, tmp_path: Path):
        """A 429 honours Retry-After and then succeeds."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        monkeypatch.setattr("time.sleep", lambda _: None)
        responses = iter(
            [_Resp({}, 429, {"Retry-After": "0"}), _Resp({"webUrl": "u"})]
        )
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: next(responses)
        )
        assert uploader.upload("d1", "R", deck) == "u"

    def test_site_convenience_method(self, uploader, monkeypatch, tmp_path: Path):
        """``upload_to_site`` chains resolution and upload."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        responses = iter(
            [_Resp({"id": "s"}), _Resp({"id": "d"}), _Resp({"webUrl": "final"})]
        )
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: next(responses)
        )
        assert uploader.upload_to_site("h", "/sites/E", "R", deck) == "final"

    def test_onedrive_convenience_method(self, uploader, monkeypatch, tmp_path: Path):
        """``upload_to_onedrive`` chains resolution and upload."""
        deck = tmp_path / "deck.pptx"
        deck.write_bytes(b"x")
        responses = iter([_Resp({"id": "d"}), _Resp({"webUrl": "final"})])
        monkeypatch.setattr(
            uploader._session, "request", lambda *a, **k: next(responses)
        )
        assert uploader.upload_to_onedrive("p@x.com", "R", deck) == "final"


class TestCliDelivery:
    """Destination validation in the CLI layer."""

    def _args(self, **overrides):
        """Build a namespace with upload defaults.

        Args:
            **overrides: Fields to override.

        Returns:
            An argparse-like namespace.
        """
        import argparse

        base = dict(
            sharepoint_host=None,
            sharepoint_site=None,
            onedrive_user=None,
            upload_folder="Sprint Reviews",
            upload_name=None,
        )
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_no_destination_is_a_noop(self, tmp_path: Path):
        """Without a destination the deck is simply left on disk."""
        from sprint_report.cli import _deliver

        _deliver(self._args(), tmp_path / "deck.pptx", "Sprint 14")

    def test_both_destinations_rejected(self, tmp_path: Path):
        """Specifying SharePoint and OneDrive together is ambiguous."""
        from sprint_report.cli import _deliver

        args = self._args(
            sharepoint_host="h", sharepoint_site="/s", onedrive_user="p@x.com"
        )
        with pytest.raises(SystemExit, match="not both"):
            _deliver(args, tmp_path / "d.pptx", "Sprint 14")

    def test_partial_sharepoint_rejected(self, tmp_path: Path):
        """Host without site cannot resolve a destination."""
        from sprint_report.cli import _deliver

        with pytest.raises(SystemExit, match="together"):
            _deliver(
                self._args(sharepoint_host="h"), tmp_path / "d.pptx", "Sprint 14"
            )

    def test_missing_credentials_named(self, tmp_path: Path, monkeypatch):
        """The error names exactly which variables are unset."""
        from sprint_report.cli import _deliver

        for var in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(SystemExit, match="GRAPH_TENANT_ID"):
            _deliver(
                self._args(sharepoint_host="h", sharepoint_site="/s"),
                tmp_path / "d.pptx",
                "Sprint 14",
            )

    def test_default_remote_name_uses_iteration(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """The remote filename defaults to '<iteration> Review.pptx'."""
        from sprint_report import cli

        monkeypatch.setenv("GRAPH_TENANT_ID", "t")
        monkeypatch.setenv("GRAPH_CLIENT_ID", "c")
        monkeypatch.setenv("GRAPH_CLIENT_SECRET", "s")
        captured = {}

        class _Stub:
            def upload_to_site(self, host, site, folder, path, name):
                captured["name"] = name
                return "https://sp/x"

        monkeypatch.setattr(cli, "_make_uploader", lambda: _Stub())
        cli._deliver(
            self._args(sharepoint_host="h", sharepoint_site="/s"),
            tmp_path / "d.pptx",
            "Sprint 14",
        )
        assert captured["name"] == "Sprint 14 Review.pptx"
        assert "Uploaded to" in capsys.readouterr().out
