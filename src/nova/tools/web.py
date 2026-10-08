import ipaddress
import socket
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

import httpx

from nova.tools.base import Tool, ToolError, object_schema

MAX_PAGE_CHARS = 15_000
MAX_REDIRECTS = 5
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) NOVA-assistant"

SearchFunction = Callable[[str, int], list[dict[str, Any]]]
Resolver = Callable[[str], list[str]]


def duckduckgo_search(region: str) -> SearchFunction:
    def search(query: str, max_results: int) -> list[dict[str, Any]]:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException

        try:
            return DDGS().text(query, region=region, max_results=max_results)
        except DDGSException as error:
            raise ToolError(f"Web search failed: {error}") from error

    return search


def resolve_host(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class WebBrowser:
    """Web search and page fetching. Pages are fetched on the public web only: never this computer
    (NOVA's own server, Ollama...) nor the local network (the box, a NAS, printers), even through a redirect."""

    def __init__(self, search: SearchFunction, http_client: httpx.Client | None = None, resolve: Resolver = resolve_host) -> None:
        self.search = search
        self.http_client = http_client or httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT})
        self.resolve = resolve

    def web_search(self, query: str, max_results: int = 5) -> str:
        results = self.search(query, max(1, min(max_results, 10)))
        if not results:
            return f"No web results for: {query}"
        return "\n\n".join(
            f"{index}. {result.get('title', '')}\n   {result.get('href', '')}\n   {result.get('body', '')}"
            for index, result in enumerate(results, start=1)
        )

    def fetch_page(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            raise ToolError("Only http:// and https:// URLs can be fetched.")
        try:
            request = self.http_client.build_request("GET", url)
            for _ in range(MAX_REDIRECTS + 1):
                self._require_public(request.url)
                response = self.http_client.send(request, follow_redirects=False)
                if response.next_request is None:
                    break
                request = response.next_request
            else:
                raise ToolError(f"Too many redirects for {url}.")
            response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as error:
            raise ToolError(f"Could not fetch {url}: {error}") from error
        content_type = response.headers.get("content-type", "")
        text = html_to_text(response.text) if "html" in content_type else response.text
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + f"\n... page truncated ({len(text)} characters in total)."
        return f"Content of {response.url}:\n\n{text}"

    def _require_public(self, url: httpx.URL) -> None:
        host = url.host
        try:
            addresses = [host] if is_ip_address(host) else self.resolve(host)
        except OSError:
            return  # Unknown name: the request itself will fail with a clear error.
        if host.lower() == "localhost" or any(not is_public_address(address) for address in addresses):
            raise ToolError(f"{host} is this computer or the local network: NOVA only fetches public web pages.")


def is_ip_address(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    return True


class _TextExtractor(HTMLParser):
    SKIPPED_TAGS = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIPPED_TAGS:
            self.skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED_TAGS and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth and data.strip():
            self.parts.append(data.strip() + " ")


def html_to_text(html: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = (line.strip() for line in "".join(extractor.parts).splitlines())
    return "\n".join(line for line in lines if line)


def build_web_tools(browser: WebBrowser) -> list[Tool]:
    return [
        Tool(
            name="web_search",
            description="Search the web (DuckDuckGo). Returns titles, URLs and snippets. Use fetch_page to read a result.",
            parameters=object_schema(
                {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "description": "1 to 10. Default 5."},
                },
                required=["query"],
            ),
            run=browser.web_search,
            reads_outside=lambda query, max_results=5: f"la recherche web « {query} »",
        ),
        Tool(
            name="fetch_page",
            description=(
                "Download a web page or API URL and return its text. "
                "For weather, https://wttr.in/<City>?format=j1&lang=fr returns current conditions and forecast as JSON."
            ),
            parameters=object_schema({"url": {"type": "string"}}, required=["url"]),
            run=browser.fetch_page,
            effect="sends",
            action="ouvrir une adresse web",
            reads_outside=lambda url: f"la page {url}",
        ),
    ]
