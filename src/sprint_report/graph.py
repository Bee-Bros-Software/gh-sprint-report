"""Microsoft Graph upload of generated decks.

Delivers the sprint review deck to a SharePoint document library or a OneDrive
folder so it is waiting where the team already works, rather than sitting in a
build artifact.

Authentication uses the OAuth 2.0 client credentials flow against an Entra ID
app registration. Prefer **Sites.Selected**, with an administrator authorising
the single target site, over the tenant-wide ``Files.ReadWrite.All`` — the
latter grants read and write across every site in the tenant, which is a lot
of authority for a tool that writes one file a week.

Example:
    >>> uploader = GraphUploader(  # doctest: +SKIP
    ...     tenant_id="...", client_id="...", client_secret="..."
    ... )
    >>> uploader.upload_to_site(  # doctest: +SKIP
    ...     hostname="contoso.sharepoint.com",
    ...     site_path="/sites/Engineering",
    ...     folder="Sprint Reviews",
    ...     local_path=Path("sprint-review.pptx"),
    ... )
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

__all__ = ["GraphUploader", "GraphError", "PPTX_CONTENT_TYPE"]

#: Microsoft Graph API root.
GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

#: OAuth token endpoint template.
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

#: MIME type for PowerPoint files.
PPTX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

#: Graph rejects a simple content PUT above roughly 4 MiB; larger files need an
#: upload session. A generated deck is typically well under 200 KiB.
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024


class GraphError(RuntimeError):
    """Raised when Microsoft Graph returns an error or authentication fails.

    Example:
        >>> raise GraphError("insufficient privileges")
        Traceback (most recent call last):
        ...
        sprint_report.graph.GraphError: insufficient privileges
    """


class GraphUploader:
    """Uploads files to SharePoint or OneDrive via Microsoft Graph.

    Args:
        tenant_id: Entra ID tenant GUID or domain.
        client_id: Application (client) ID of the app registration.
        client_secret: Client secret for that registration.
        timeout: Per-request timeout in seconds.
        max_retries: Attempts made before giving up on transient failures.

    Raises:
        ValueError: If any credential is empty.

    Example:
        >>> GraphUploader("t", "c", "s").timeout
        30.0
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        """Initialise the uploader. See class docstring for argument meanings."""
        if not all((tenant_id, client_id, client_secret)):
            raise ValueError(
                "tenant_id, client_id, and client_secret are all required"
            )
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self.timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _access_token(self) -> str:
        """Return a valid access token, fetching or refreshing as needed.

        Tokens are cached until 60 seconds before expiry so a run that uploads
        several files does not re-authenticate each time.

        Returns:
            A bearer token string.

        Raises:
            GraphError: If the token endpoint rejects the credentials.
        """
        if self._token and time.time() < self._token_expires_at:
            return self._token

        response = self._session.post(
            TOKEN_URL.format(tenant=self._tenant_id),
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise GraphError(
                f"Token request failed ({response.status_code}): "
                f"{response.text[:300]}"
            )
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise GraphError("Token response contained no access_token")

        self._token = str(token)
        self._token_expires_at = time.time() + float(payload.get("expires_in", 3600)) - 60
        return self._token

    # ------------------------------------------------------------------
    # Request plumbing
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        """Issue an authenticated Graph request with retries.

        Args:
            method: HTTP verb.
            url: Absolute Graph URL.
            data: Optional request body for uploads.
            content_type: Content type accompanying ``data``.

        Returns:
            The decoded JSON response, or an empty dict for empty bodies.

        Raises:
            GraphError: On HTTP failure or exhausted retries.
        """
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        if content_type:
            headers["Content-Type"] = content_type

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.request(
                    method, url, headers=headers, data=data, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
                continue

            if response.status_code in (429, 503, 504):
                last_error = GraphError(f"HTTP {response.status_code}")
                time.sleep(float(response.headers.get("Retry-After", 2**attempt)))
                continue
            if response.status_code >= 400:
                raise GraphError(
                    f"Graph {method} {url} failed ({response.status_code}): "
                    f"{response.text[:300]}"
                )
            if not response.content:
                return {}
            return dict(response.json())

        raise GraphError(f"Giving up after {self._max_retries} attempts: {last_error}")

    # ------------------------------------------------------------------
    # Resource resolution
    # ------------------------------------------------------------------

    def resolve_site_drive(self, hostname: str, site_path: str) -> str:
        """Look up the default document library of a SharePoint site.

        Args:
            hostname: SharePoint host, e.g. ``"contoso.sharepoint.com"``.
            site_path: Server-relative site path, e.g. ``"/sites/Engineering"``.

        Returns:
            The drive ID of the site's default document library.

        Raises:
            GraphError: If the site or its drive cannot be read.

        Example:
            >>> GraphUploader("t", "c", "s").resolve_site_drive(  # doctest: +SKIP
            ...     "contoso.sharepoint.com", "/sites/Eng")
            'b!abc...'
        """
        path = site_path if site_path.startswith("/") else f"/{site_path}"
        site = self._request("GET", f"{GRAPH_ROOT}/sites/{hostname}:{path}")
        site_id = site.get("id")
        if not site_id:
            raise GraphError(f"No site found at {hostname}{path}")
        drive = self._request("GET", f"{GRAPH_ROOT}/sites/{site_id}/drive")
        drive_id = drive.get("id")
        if not drive_id:
            raise GraphError(f"Site {hostname}{path} has no default document library")
        return str(drive_id)

    def resolve_user_drive(self, user_principal_name: str) -> str:
        """Look up a user's OneDrive.

        Args:
            user_principal_name: The user's UPN, e.g. ``"phil@contoso.com"``.

        Returns:
            The drive ID of that user's OneDrive.

        Raises:
            GraphError: If the user or drive cannot be read.

        Example:
            >>> GraphUploader("t", "c", "s").resolve_user_drive(  # doctest: +SKIP
            ...     "phil@contoso.com")
            'b!xyz...'
        """
        drive = self._request(
            "GET", f"{GRAPH_ROOT}/users/{user_principal_name}/drive"
        )
        drive_id = drive.get("id")
        if not drive_id:
            raise GraphError(f"No OneDrive found for {user_principal_name}")
        return str(drive_id)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    def upload(
        self,
        drive_id: str,
        folder: str,
        local_path: Path,
        remote_name: str | None = None,
    ) -> str:
        """Upload a file into a drive folder, replacing any file of that name.

        Args:
            drive_id: Target drive ID.
            folder: Folder path within the drive, e.g. ``"Sprint Reviews"``.
                Use an empty string for the drive root. Created if absent.
            local_path: File to upload.
            remote_name: Filename to use remotely; defaults to the local name.

        Returns:
            The web URL of the uploaded item.

        Raises:
            FileNotFoundError: If ``local_path`` does not exist.
            GraphError: If the file exceeds the simple-upload limit or the
                upload is rejected.

        Example:
            >>> GraphUploader("t", "c", "s").upload(  # doctest: +SKIP
            ...     "b!abc", "Sprint Reviews", Path("deck.pptx"))
            'https://contoso.sharepoint.com/...'
        """
        if not local_path.exists():
            raise FileNotFoundError(local_path)

        payload = local_path.read_bytes()
        if len(payload) > SIMPLE_UPLOAD_LIMIT:
            raise GraphError(
                f"{local_path.name} is {len(payload)} bytes, above the "
                f"{SIMPLE_UPLOAD_LIMIT}-byte simple upload limit. "
                "An upload session would be required."
            )

        name = remote_name or local_path.name
        segment = f"{folder.strip('/')}/{name}" if folder.strip("/") else name
        url = f"{GRAPH_ROOT}/drives/{drive_id}/root:/{segment}:/content"

        item = self._request(
            "PUT", url, data=payload, content_type=PPTX_CONTENT_TYPE
        )
        return str(item.get("webUrl", ""))

    def upload_to_site(
        self,
        hostname: str,
        site_path: str,
        folder: str,
        local_path: Path,
        remote_name: str | None = None,
    ) -> str:
        """Resolve a SharePoint site and upload into its document library.

        Args:
            hostname: SharePoint host.
            site_path: Server-relative site path.
            folder: Folder within the default document library.
            local_path: File to upload.
            remote_name: Filename to use remotely.

        Returns:
            The web URL of the uploaded item.

        Raises:
            GraphError: If the site cannot be resolved or the upload fails.

        Example:
            >>> GraphUploader("t", "c", "s").upload_to_site(  # doctest: +SKIP
            ...     "contoso.sharepoint.com", "/sites/Eng", "Reviews",
            ...     Path("deck.pptx"))
            'https://contoso.sharepoint.com/...'
        """
        drive_id = self.resolve_site_drive(hostname, site_path)
        return self.upload(drive_id, folder, local_path, remote_name)

    def upload_to_onedrive(
        self,
        user_principal_name: str,
        folder: str,
        local_path: Path,
        remote_name: str | None = None,
    ) -> str:
        """Resolve a user's OneDrive and upload into it.

        Args:
            user_principal_name: The owning user's UPN.
            folder: Folder within the OneDrive.
            local_path: File to upload.
            remote_name: Filename to use remotely.

        Returns:
            The web URL of the uploaded item.

        Raises:
            GraphError: If the drive cannot be resolved or the upload fails.

        Example:
            >>> GraphUploader("t", "c", "s").upload_to_onedrive(  # doctest: +SKIP
            ...     "phil@contoso.com", "Reviews", Path("deck.pptx"))
            'https://contoso-my.sharepoint.com/...'
        """
        drive_id = self.resolve_user_drive(user_principal_name)
        return self.upload(drive_id, folder, local_path, remote_name)
