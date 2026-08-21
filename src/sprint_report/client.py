"""GitHub Projects v2 GraphQL client.

Reads an organization project board and converts its items into
:class:`~sprint_report.models.ProjectItem` instances. Only read
operations are performed; the tool never writes to the board.

The API token must be a fine-grained personal access token or GitHub App
installation token with **organization Projects: read** permission. The
``GITHUB_TOKEN`` provided to Actions workflows does *not* carry that scope and
will fail with a permission error.

Example:
    >>> client = ProjectsClient(token="ghp_example")  # doctest: +SKIP
    >>> project_id = client.resolve_project_id("resolve-systems", 4)  # doctest: +SKIP
    >>> items = client.fetch_items(project_id)  # doctest: +SKIP
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import requests

from .models import ProjectItem, _parse_date

__all__ = ["ProjectsClient", "GitHubApiError", "FieldMapping"]

#: Default GitHub GraphQL endpoint.
GRAPHQL_URL = "https://api.github.com/graphql"

_PROJECT_ID_QUERY = """
query($org: String!, $number: Int!) {
  organization(login: $org) {
    projectV2(number: $number) { id title }
  }
}
"""

_ITEMS_QUERY = """
query($projectId: ID!, $after: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      title
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          content {
            __typename
            ... on Issue {
              title url state closedAt
              repository { nameWithOwner }
              milestone { title }
            }
            ... on PullRequest {
              title url state closedAt
              repository { nameWithOwner }
              milestone { title }
            }
            ... on DraftIssue { title }
          }
          fieldValues(first: 30) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldTextValue {
                text field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldNumberValue {
                number field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                name field { ... on ProjectV2FieldCommon { name } }
              }
              ... on ProjectV2ItemFieldIterationValue {
                title startDate duration
                field { ... on ProjectV2FieldCommon { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


class GitHubApiError(RuntimeError):
    """Raised when the GitHub GraphQL API returns errors or an HTTP failure.

    Example:
        >>> raise GitHubApiError("bad credentials")
        Traceback (most recent call last):
        ...
        sprint_report.client.GitHubApiError: bad credentials
    """


class FieldMapping:
    """Names of the board fields this tool reads.

    Board fields are addressed by display name, so a team that calls its
    estimate field something other than ``Pts`` can override the mapping
    rather than renaming the field.

    Attributes:
        points: Name of the numeric estimate field.
        origin: Name of the single-select planned/unplanned/carryover field.
        status: Name of the status field.
        iteration: Name of the iteration field.

    Example:
        >>> FieldMapping(points="Story Points").points
        'Story Points'
    """

    def __init__(
        self,
        points: str = "Pts",
        origin: str = "Origin",
        status: str = "Status",
        iteration: str = "Sprint",
    ) -> None:
        """Initialise a field mapping.

        Args:
            points: Numeric estimate field name.
            origin: Work-origin single-select field name.
            status: Status field name.
            iteration: Iteration field name.
        """
        self.points = points
        self.origin = origin
        self.status = status
        self.iteration = iteration


class ProjectsClient:
    """Thin, retrying GraphQL client scoped to Projects v2 reads.

    Args:
        token: A token with organization Projects read permission.
        endpoint: GraphQL endpoint; overridable for GitHub Enterprise Server.
        fields: Board field name mapping.
        timeout: Per-request timeout in seconds.
        max_retries: Attempts made before giving up on transient failures.

    Example:
        >>> ProjectsClient(token="x").fields.points
        'Pts'
    """

    def __init__(
        self,
        token: str,
        endpoint: str = GRAPHQL_URL,
        fields: FieldMapping | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        """Initialise the client. See class docstring for argument meanings."""
        if not token:
            raise ValueError("A GitHub token is required")
        self._token = token
        self._endpoint = endpoint
        self.fields = fields or FieldMapping()
        self._timeout = timeout
        self._max_retries = max_retries
        self._session = requests.Session()

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute a GraphQL query with retries on transient failures.

        Args:
            query: The GraphQL document.
            variables: Query variables.

        Returns:
            The ``data`` object from the response body.

        Raises:
            GitHubApiError: On HTTP failure, GraphQL errors, or exhausted
                retries.
        """
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                response = self._session.post(
                    self._endpoint,
                    json={"query": query, "variables": variables},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                    },
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(2**attempt)
                continue

            if response.status_code in (502, 503, 504):
                last_error = GitHubApiError(f"HTTP {response.status_code}")
                time.sleep(2**attempt)
                continue
            if response.status_code >= 400:
                raise GitHubApiError(
                    f"HTTP {response.status_code} from GitHub: {response.text[:300]}"
                )

            body = response.json()
            if body.get("errors"):
                messages = "; ".join(
                    err.get("message", "unknown") for err in body["errors"]
                )
                raise GitHubApiError(f"GraphQL error: {messages}")
            return body.get("data") or {}

        raise GitHubApiError(
            f"Giving up after {self._max_retries} attempts: {last_error}"
        )

    def resolve_project_id(self, org: str, number: int) -> str:
        """Look up a project's node ID from its org and board number.

        Args:
            org: Organization login, e.g. ``"resolve-systems"``.
            number: The project number shown in the board URL.

        Returns:
            The ``ProjectV2`` node ID.

        Raises:
            GitHubApiError: If the organization or project cannot be found.

        Example:
            >>> ProjectsClient("x").resolve_project_id("org", 1)  # doctest: +SKIP
            'PVT_kwDO...'
        """
        data = self._post(_PROJECT_ID_QUERY, {"org": org, "number": number})
        org_node = data.get("organization") or {}
        project = org_node.get("projectV2")
        if not project:
            raise GitHubApiError(f"No project #{number} found in organization {org!r}")
        return str(project["id"])

    def fetch_items(self, project_id: str) -> tuple[str, list[ProjectItem]]:
        """Fetch every item on a board, following pagination.

        Args:
            project_id: The ``ProjectV2`` node ID.

        Returns:
            A tuple of the board title and the list of items.

        Raises:
            GitHubApiError: If the board cannot be read.

        Example:
            >>> ProjectsClient("x").fetch_items("PVT_1")  # doctest: +SKIP
            ('Acme Delivery', [...])
        """
        items: list[ProjectItem] = []
        title = ""
        for page in self._iter_pages(project_id):
            title = page.get("title") or title
            for node in page.get("items", {}).get("nodes", []) or []:
                parsed = self._parse_item(node)
                if parsed is not None:
                    items.append(parsed)
        return title, items

    def _iter_pages(self, project_id: str) -> Iterator[dict[str, Any]]:
        """Yield each page of the items connection.

        Args:
            project_id: The ``ProjectV2`` node ID.

        Yields:
            The ``node`` object from each paginated response.

        Raises:
            GitHubApiError: If the node is not a readable project.
        """
        cursor: str | None = None
        while True:
            data = self._post(_ITEMS_QUERY, {"projectId": project_id, "after": cursor})
            node = data.get("node")
            if not node:
                raise GitHubApiError(f"Project {project_id!r} not found or not visible")
            yield node
            page_info = node.get("items", {}).get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                return
            cursor = page_info.get("endCursor")

    def _parse_item(self, node: dict[str, Any]) -> ProjectItem | None:
        """Convert one GraphQL item node into a :class:`ProjectItem`.

        Args:
            node: A single element of the ``items.nodes`` array.

        Returns:
            The parsed item, or ``None`` if the node carries no content
            (which happens for items the token cannot see).

        Example:
            >>> ProjectsClient("x")._parse_item({"id": "1", "content": None})
        """
        content = node.get("content") or {}
        if not content:
            return None

        values = self._index_field_values(node)
        iteration = values.get(self.fields.iteration, {})
        repository = (content.get("repository") or {}).get("nameWithOwner", "")
        milestone = (content.get("milestone") or {}).get("title")

        return ProjectItem(
            item_id=str(node.get("id", "")),
            title=str(content.get("title", "")),
            url=str(content.get("url", "")),
            status=str(values.get(self.fields.status, {}).get("value") or ""),
            iteration=iteration.get("value"),
            iteration_start=_parse_date(iteration.get("startDate")),
            iteration_duration=iteration.get("duration"),
            points=values.get(self.fields.points, {}).get("value"),
            origin=values.get(self.fields.origin, {}).get("value"),
            closed=str(content.get("state", "")).upper() == "CLOSED",
            closed_at=_parse_date(content.get("closedAt")),
            milestone=milestone,
            repository=repository,
        )

    @staticmethod
    def _index_field_values(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Index an item's field values by field display name.

        Args:
            node: A single element of the ``items.nodes`` array.

        Returns:
            A mapping of field name to a dict carrying at least ``value``, plus
            ``startDate`` and ``duration`` for iteration fields.

        Example:
            >>> ProjectsClient._index_field_values({"fieldValues": {"nodes": []}})
            {}
        """
        indexed: dict[str, dict[str, Any]] = {}
        for value_node in node.get("fieldValues", {}).get("nodes", []) or []:
            field_name = (value_node.get("field") or {}).get("name")
            if not field_name:
                continue
            typename = value_node.get("__typename", "")
            if typename == "ProjectV2ItemFieldNumberValue":
                indexed[field_name] = {"value": value_node.get("number")}
            elif typename == "ProjectV2ItemFieldSingleSelectValue":
                indexed[field_name] = {"value": value_node.get("name")}
            elif typename == "ProjectV2ItemFieldIterationValue":
                indexed[field_name] = {
                    "value": value_node.get("title"),
                    "startDate": value_node.get("startDate"),
                    "duration": value_node.get("duration"),
                }
            elif typename == "ProjectV2ItemFieldTextValue":
                indexed[field_name] = {"value": value_node.get("text")}
        return indexed
