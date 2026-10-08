import httpx
import pytest

from nova.tools.base import ToolError
from nova.tools.web import WebBrowser, html_to_text


def fake_search(results):
    calls = []

    def search(query, max_results):
        calls.append((query, max_results))
        return results

    search.calls = calls
    return search


PUBLIC_ADDRESS = "93.184.215.14"


def browser_with_pages(handler, addresses: dict[str, str] | None = None) -> WebBrowser:
    """`addresses` maps host names to the IP the fake DNS returns (a public one by default)."""
    resolve = lambda host: [(addresses or {}).get(host, PUBLIC_ADDRESS)]  # noqa: E731
    return WebBrowser(fake_search([]), http_client=httpx.Client(transport=httpx.MockTransport(handler)), resolve=resolve)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8765/api/status", "http://localhost:11434/api/tags", "http://192.168.1.1/", "http://[::1]/",
     "http://169.254.169.254/latest/meta-data/", "http://10.0.0.5/", "http://[::ffff:192.168.0.1]/"],
)
def test_this_computer_and_the_local_network_are_never_fetched(url: str):
    reached = []
    browser = browser_with_pages(lambda request: reached.append(request) or httpx.Response(200, text="secret"))
    with pytest.raises(ToolError, match="local network"):
        browser.fetch_page(url)
    assert reached == []


def test_a_name_resolving_to_a_private_address_is_refused():
    browser = browser_with_pages(lambda request: httpx.Response(200, text="box"), addresses={"box.example": "192.168.1.254"})
    with pytest.raises(ToolError, match="local network"):
        browser.fetch_page("https://box.example/admin")


def test_a_redirect_to_the_local_network_is_refused():
    reached = []

    def handler(request: httpx.Request) -> httpx.Response:
        reached.append(str(request.url))
        if request.url.host == "short.example":
            return httpx.Response(302, headers={"location": "http://192.168.1.1/admin"})
        return httpx.Response(200, text="admin")

    with pytest.raises(ToolError, match="local network"):
        browser_with_pages(handler).fetch_page("https://short.example/x")
    assert reached == ["https://short.example/x"]


def test_public_redirects_are_followed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, text="nouvelle page", headers={"content-type": "text/plain"})

    assert browser_with_pages(handler).fetch_page("https://site.example/old").startswith("Content of https://site.example/new")


def test_web_search_formats_results():
    search = fake_search([{"title": "Météo Paris", "href": "https://meteo.example/paris", "body": "Soleil, 21°C"}])
    output = WebBrowser(search).web_search("météo Paris")
    assert "1. Météo Paris" in output and "https://meteo.example/paris" in output and "21°C" in output


def test_web_search_caps_max_results():
    search = fake_search([])
    WebBrowser(search).web_search("x", max_results=50)
    assert search.calls == [("x", 10)]


def test_web_search_without_results():
    assert "No web results" in WebBrowser(fake_search([])).web_search("zzz")


def test_fetch_page_extracts_text_from_html():
    html = "<html><head><title>t</title><script>var a=1;</script></head><body><h1>Paris</h1><p>21°C sunny</p></body></html>"
    browser = browser_with_pages(lambda request: httpx.Response(200, html=html))
    output = browser.fetch_page("https://meteo.example/paris")
    assert "Paris" in output and "21°C sunny" in output and "var a" not in output


def test_fetch_page_returns_json_as_is():
    browser = browser_with_pages(lambda request: httpx.Response(200, json={"temp_C": "21"}))
    assert '"temp_C"' in browser.fetch_page("https://wttr.in/Paris?format=j1")


def test_fetch_page_http_error_becomes_tool_error():
    browser = browser_with_pages(lambda request: httpx.Response(404))
    with pytest.raises(ToolError, match="Could not fetch"):
        browser.fetch_page("https://example.com/missing")


def test_fetch_page_rejects_non_http_urls():
    with pytest.raises(ToolError):
        browser_with_pages(lambda request: httpx.Response(200)).fetch_page("file:///etc/passwd")


def test_html_to_text_keeps_blocks_on_separate_lines():
    assert html_to_text("<p>one</p><p>two</p>") == "one\ntwo"
