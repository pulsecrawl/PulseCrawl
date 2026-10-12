"""Small fictional HTTP input for offline quickstarts; never opens a socket."""

from datetime import datetime, timezone
from urllib.parse import urlsplit

from pulsecrawl.domain.crawling.model import FetchResult

EXAMPLE_URL = "https://quickstart.example/articles/hello"
FIELDS = [
    {"fieldId": "title", "name": "title", "type": "string"},
    {"fieldId": "description", "name": "description", "type": "string"},
]
MAPPINGS = {
    "title": ["og:title", "<title>"],
    "description": ["og:description", "description"],
}
HTML = (
    '<title>Hello PulseCrawl</title><meta name="description" content="Offline example">'
)


class FixtureFetcher:
    async def fetch(self, url, *, user_agent):
        if url == EXAMPLE_URL:
            status, body = 200, HTML
        elif (
            urlsplit(url).hostname == "quickstart.example"
            and urlsplit(url).path == "/robots.txt"
        ):
            status, body = 200, "User-agent: *\nAllow: /\n"
        else:
            status, body = 404, None
        return FetchResult(
            url=url,
            final_url=url,
            status=status,
            body=body,
            headers={},
            error=None if status == 200 else "not an offline fixture URL",
            fetched_at=datetime.now(timezone.utc),
        )
