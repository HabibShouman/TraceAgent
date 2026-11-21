"""Bounded public-web access and text extraction for research tools."""

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import multiprocessing
import re
import socket
import ssl
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from urllib.request import getproxies, proxy_bypass

from .tools import ToolError


MAX_BYTES = 8 * 1024 * 1024
MAX_PDF_PAGES = 40
MAX_DOCUMENT_CHARS = 160_000
SEARCH_BACKENDS = "duckduckgo,bing"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_url(url: str) -> str:
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise ToolError("invalid_url", "Provide an HTTP(S) URL of at most 2048 characters.")
    try:
        parts = urlsplit(url)
        hostname = (parts.hostname or "").encode("idna").decode("ascii").lower()
        port = parts.port
    except (ValueError, UnicodeError):
        raise ToolError("invalid_url", "The URL could not be parsed.") from None
    if parts.scheme not in {"http", "https"} or not hostname or parts.username or parts.password:
        raise ToolError("invalid_url", "Use an HTTP(S) URL without embedded credentials.")
    if port not in (None, 80 if parts.scheme == "http" else 443):
        raise ToolError("blocked_url", "Only the standard HTTP and HTTPS ports are supported.")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise ToolError("blocked_url", "Local and internal addresses cannot be read.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ToolError("blocked_url", "Only public internet addresses can be read.")
    if re.search(r"(?i)(?:^|&)(?:key|api[_-]?key|token|access_token|signature)=", parts.query):
        raise ToolError("blocked_url", "URLs containing credential-like query parameters are not supported.")
    host = f"[{hostname}]" if ":" in hostname else hostname
    return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))


def resolve_public(hostname: str, port: int) -> str:
    try:
        addresses = list(dict.fromkeys(item[4][0] for item in socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)))
    except OSError:
        raise ToolError("dns_error", "The source hostname could not be resolved.") from None
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ToolError("blocked_url", "The source resolves to a non-public internet address.")
    return sorted(addresses, key=lambda address: ipaddress.ip_address(address).version)[0]


@dataclass
class Download:
    url: str
    content_type: str
    data: bytes


def proxy_for(url: str) -> str | None:
    parts = urlsplit(url)
    if proxy_bypass(parts.hostname):
        return None
    proxies = getproxies()
    return proxies.get(parts.scheme) or proxies.get("all")


def response_body(status: int, headers, chunks) -> bytes:
    if status != 200:
        raise ToolError("source_http_error", f"The source returned HTTP {status}.")
    if headers.get("content-encoding", headers.get("Content-Encoding", "identity")).lower() not in ("", "identity"):
        raise ToolError("unsupported_encoding", "The source did not provide an uncompressed response.")
    length = headers.get("content-length", headers.get("Content-Length", ""))
    if length.isdigit() and int(length) > MAX_BYTES:
        raise ToolError("source_too_large", "The source exceeds the 8 MiB download limit.")
    parts, size = [], 0
    for chunk in chunks:
        size += len(chunk)
        if size > MAX_BYTES:
            raise ToolError("source_too_large", "The source exceeds the 8 MiB download limit.")
        parts.append(chunk)
    return b"".join(parts)


def proxy_get(url: str, proxy: str) -> tuple[int, dict, bytes]:
    import httpx

    try:
        with httpx.Client(proxy=proxy, timeout=httpx.Timeout(15, connect=10), follow_redirects=False) as client:
            with client.stream("GET", url, headers={"User-Agent": "TraceAgent/0.1 research", "Accept-Encoding": "identity"}) as response:
                headers = dict(response.headers)
                if response.status_code in (301, 302, 303, 307, 308):
                    return response.status_code, headers, b""
                return response.status_code, headers, response_body(response.status_code, headers, response.iter_raw(64 * 1024))
    except httpx.HTTPError:
        raise ToolError("source_unavailable", "The source could not be downloaded through the configured proxy.") from None


def download(url: str) -> Download:
    """Validate public destinations; pin direct connections and honor trusted proxies."""
    import certifi
    import urllib3

    current = public_url(url)
    for _ in range(4):
        parts = urlsplit(current)
        hostname = parts.hostname
        port = 443 if parts.scheme == "https" else 80
        address = resolve_public(hostname, port)
        proxy = proxy_for(current)
        if proxy:
            status, headers, data = proxy_get(current, proxy)
            if status in (301, 302, 303, 307, 308):
                location = headers.get("location")
                if not location:
                    raise ToolError("redirect_error", "The source redirected without a destination.")
                current = public_url(urljoin(current, location))
                continue
            return Download(current, headers.get("content-type", "").split(";")[0].lower(), data)
        options = {"host": address, "port": port, "timeout": urllib3.Timeout(connect=5, read=15)}
        tls_options = {
            "server_hostname": hostname, "assert_hostname": hostname,
            "cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where(),
        } if parts.scheme == "https" else {}
        if parts.scheme == "https":
            pool = urllib3.HTTPSConnectionPool(**options, **tls_options)
        else:
            pool = urllib3.HTTPConnectionPool(**options)
        target = quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
        if parts.query:
            target += "?" + quote(parts.query, safe="%=&?/:@!$'()*+,;-._~")
        response = None
        try:
            response = pool.urlopen(
                "GET", target, headers={"Host": hostname, "User-Agent": "TraceAgent/0.1 research", "Accept-Encoding": "identity"},
                preload_content=False, redirect=False, retries=False,
            )
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ToolError("redirect_error", "The source redirected without a destination.")
                current = public_url(urljoin(current, location))
                continue
            data = response_body(response.status, response.headers, response.stream(64 * 1024, decode_content=False))
            return Download(current, response.headers.get("Content-Type", "").split(";")[0].lower(), data)
        except ToolError:
            raise
        except (OSError, urllib3.exceptions.HTTPError):
            raise ToolError("source_unavailable", "The source could not be downloaded within the network limits.") from None
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ToolError("redirect_limit", "The source exceeded the redirect limit.")


class PageMetadata(HTMLParser):
    def __init__(self, url: str):
        super().__init__(convert_charrefs=True)
        self.url, self.title, self.links = url, "", []
        self.in_title = False
        self.href = None
        self.link_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.link_text = ""

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.href:
            self.link_text += data

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "a" and self.href:
            target = urljoin(self.url, self.href)
            if urlsplit(target).scheme in {"http", "https"}:
                self.links.append({"title": " ".join(self.link_text.split())[:160], "url": target[:2048]})
            self.href = None


def _worker_entry(connection, function, args):
    try:
        connection.send({"ok": True, "value": function(*args)})
    except Exception:
        connection.send({"ok": False})
    finally:
        connection.close()


def bounded_worker(function, args: tuple, timeout: int = 25):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_worker_entry, args=(sender, function, args), daemon=True)
    process.start()
    sender.close()
    try:
        if not receiver.poll(timeout):
            raise ToolError("worker_timeout", "The search or document operation exceeded its time limit.")
        message = receiver.recv()
        if not message.get("ok"):
            raise ToolError("operation_failed", "The search or document operation failed; try another source or query.")
        return message["value"]
    except EOFError:
        raise ToolError("operation_failed", "The search or document worker stopped unexpectedly.") from None
    finally:
        receiver.close()
        process.join(timeout=0.2)
        if process.is_alive():
            process.terminate()
            process.join(timeout=1)


def _search(query: str, count: int) -> list[dict]:
    from ddgs import DDGS

    return list(DDGS(proxy=proxy_for("https://duckduckgo.com/"), timeout=10).text(query, max_results=count, backend=SEARCH_BACKENDS))[:count]


def search(query: str, count: int) -> list[dict]:
    return bounded_worker(_search, (query, count))


def tavily_search(query: str, count: int, api_key: str) -> list[dict]:
    """Basic search only: one credit per request, no generated answer or upgrades."""
    import httpx

    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "query": query, "max_results": count, "search_depth": "basic",
                    "topic": "general", "include_answer": False,
                    "include_raw_content": False, "auto_parameters": False,
                },
            )
        if response.status_code in (401, 403):
            raise ToolError("search_auth", "The configured search key was rejected. Stop and check the local search configuration.")
        if response.status_code in (429, 432, 433):
            raise ToolError("search_quota", "The search quota or rate limit was reached. Stop; no paid fallback is enabled.")
        if response.status_code != 200:
            raise ToolError("search_unavailable", f"The search service returned HTTP {response.status_code}.")
        if len(response.content) > 1024 * 1024:
            raise ToolError("search_response", "The search response exceeded its size limit.")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise ToolError("search_response", "The search service returned an unexpected response.")
        return [{"title": item.get("title", ""), "url": item.get("url", ""), "body": item.get("content", "")} for item in payload["results"][:count] if isinstance(item, dict)]
    except httpx.HTTPError:
        raise ToolError("search_unavailable", "The search service could not be reached within its time limit.") from None
    except ValueError as error:
        if isinstance(error, ToolError):
            raise
        raise ToolError("search_response", "The search service returned invalid JSON.") from None


def serper_search(query: str, count: int, api_key: str) -> list[dict]:
    """One standard web search; return organic discovery hints only."""
    import httpx

    try:
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            response = client.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key},
                json={"q": query, "num": count},
            )
        if response.status_code in (401, 403):
            raise ToolError("search_auth", "The configured search key was rejected. Stop and check the local search configuration.")
        if response.status_code in (402, 429):
            raise ToolError("search_quota", "The search balance or rate limit was reached. Stop; no paid fallback is enabled.")
        if response.status_code != 200:
            raise ToolError("search_unavailable", f"The search service returned HTTP {response.status_code}.")
        if len(response.content) > 1024 * 1024:
            raise ToolError("search_response", "The search response exceeded its size limit.")
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("organic"), list):
            raise ToolError("search_response", "The search service returned an unexpected response.")
        return [{"title": item.get("title", ""), "url": item.get("link", ""), "body": item.get("snippet", "")} for item in payload["organic"][:count] if isinstance(item, dict)]
    except httpx.HTTPError:
        raise ToolError("search_unavailable", "The search service could not be reached within its time limit.") from None
    except ValueError as error:
        if isinstance(error, ToolError):
            raise
        raise ToolError("search_response", "The search service returned invalid JSON.") from None


def _pdf_text(data: bytes) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(data), strict=False)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDF")
    pages, characters, truncated = [], 0, False
    total = len(reader.pages)
    for index in range(min(total, MAX_PDF_PAGES)):
        raw_text = reader.pages[index].extract_text() or ""
        truncated = truncated or len(raw_text) > 12_000
        text = raw_text[:12_000]
        pages.append({"page": index + 1, "text": text})
        characters += len(text)
        if characters >= MAX_DOCUMENT_CHARS:
            break
    return {"pages": pages, "total_pages": total, "pages_scanned": len(pages), "truncated": truncated or len(pages) < total}


def parse_document(item: Download) -> dict:
    if item.data.lstrip().startswith(b"%PDF-") or item.content_type == "application/pdf":
        extracted = bounded_worker(_pdf_text, (item.data,))
        return {"title": urlsplit(item.url).path.rsplit("/", 1)[-1], "kind": "pdf", "links": [], **extracted}
    if item.content_type not in {"", "text/html", "application/xhtml+xml", "text/plain", "application/json"}:
        raise ToolError("unsupported_source", "This tool reads HTML, plain text, JSON, and text-based PDF sources.")
    if item.content_type in {"text/plain", "application/json"}:
        text = item.data.decode("utf-8", errors="replace")
        return {"title": item.url, "kind": "text", "links": [], "pages": [{"page": None, "text": text[:MAX_DOCUMENT_CHARS]}], "truncated": len(text) > MAX_DOCUMENT_CHARS}
    import trafilatura

    metadata = PageMetadata(item.url)
    metadata.feed(item.data.decode("utf-8", errors="replace"))
    text = trafilatura.extract(item.data, include_comments=False, include_tables=True) or ""
    if not text.strip():
        raise ToolError("no_readable_text", "No readable source text was found; try another source.")
    links = list({link["url"]: link for link in metadata.links}.values())
    # Relevant document links are often near the end of an article.
    links.sort(key=lambda link: (".pdf" not in link["url"].lower(), not bool(link["title"])))
    return {"title": " ".join(metadata.title.split())[:200] or item.url, "kind": "html", "links": links[:25], "pages": [{"page": None, "text": text[:MAX_DOCUMENT_CHARS]}], "truncated": len(text) > MAX_DOCUMENT_CHARS}


def passages(document: dict, focus: str, limit: int = 10_000) -> tuple[list[dict], bool]:
    """Select bounded passages, keeping page locations and source wording."""
    terms = set(re.findall(r"[\w.-]{3,}", focus.casefold()))
    chunks = []
    for page in document["pages"]:
        text = page["text"]
        # Overlapping windows also work for PDFs with few paragraph boundaries.
        for start in range(0, len(text), 900):
            chunk = text[start:start + 1200]
            score = sum(chunk.casefold().count(term) for term in terms)
            chunks.append({"page": page["page"], "text": chunk, "score": score, "order": len(chunks)})
    if not chunks:
        raise ToolError("no_readable_text", "No readable text was found; scanned PDFs may need OCR.")
    chosen, used = [], 0
    for chunk in sorted(chunks, key=lambda chunk: (-chunk["score"], chunk["order"])):
        if used >= limit:
            break
        text = chunk["text"][:limit - used]
        chosen.append({"page": chunk["page"], "text": text, "order": chunk["order"]})
        used += len(text)
    chosen.sort(key=lambda chunk: chunk["order"])
    return [{"page": chunk["page"], "text": chunk["text"]} for chunk in chosen], used < sum(len(chunk["text"]) for chunk in chunks)
