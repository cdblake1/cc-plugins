"""GitHub source — surfaces new/relevant AI repos via the repo search API.

Free; an optional GITHUB_TOKEN (e.g. the Actions token) raises rate limits. Content is the
repo's description + topics + language + stars, which the summarizer turns into a "what this
tool is / key facts" brief. content_type="repo".
"""

from __future__ import annotations

import json
import os
import urllib.parse

from .. import net
from ..models import FetchParams, SourceItem
from .base import ContentUnavailable, Source

API = "https://api.github.com/search/repositories"


class GitHubSource(Source):
    name = "github"

    def discover(self, params: FetchParams) -> list[SourceItem]:
        q = params.topic.strip()
        if params.since:
            q += f" created:>={params.since[:10]}"
        if params.until:
            q += f" created:<{params.until[:10]}"
        query = {
            "q": q,
            "sort": "stars",
            "order": "desc",
            "per_page": str(max(1, params.max_results)),
        }
        url = f"{API}?{urllib.parse.urlencode(query)}"
        headers = {"Accept": "application/vnd.github+json"}
        token = os.environ.get("GITHUB_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            data = json.loads(net.get(url, headers=headers))
        except (net.HTTPError, net.URLError, OSError, json.JSONDecodeError):
            return []

        items: list[SourceItem] = []
        for repo in data.get("items", []):
            full = repo.get("full_name") or ""
            desc = (repo.get("description") or "").strip()
            topics = ", ".join(repo.get("topics", []) or [])
            text = (
                f"{full} — {desc}\n"
                f"Language: {repo.get('language') or 'n/a'} · Stars: {repo.get('stargazers_count', 0)}"
                + (f"\nTopics: {topics}" if topics else "")
            ).strip()
            items.append(
                SourceItem(
                    source=self.name,
                    external_id=str(repo.get("id") or full),
                    url=repo.get("html_url") or f"https://github.com/{full}",
                    title=full or None,
                    author=(repo.get("owner") or {}).get("login"),
                    publish_date=(repo.get("created_at") or "")[:10] or None,
                    content_type="repo",
                    meta={"text": text, "stars": repo.get("stargazers_count", 0)},
                )
            )
        return items

    def fetch_content(self, item: SourceItem) -> tuple[str, str | None]:
        text = (item.meta or {}).get("text", "").strip()
        if not text:
            raise ContentUnavailable(f"empty repo {item.external_id}")
        return text, None
