"""Read-only web access: search Wikipedia and read a page summary.

Nothing is posted anywhere. Only a search query leaves your PC.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

UA = "OlympusWorld/1.0 (personal hobby project; read-only)"
SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/"


class SearchError(Exception):
    pass


def _get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.length is not None and resp.length > 2_000_000:
                raise SearchError("page too large")
            return json.loads(resp.read(2_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        raise SearchError(f"HTTP {e.code}")
    except urllib.error.URLError as e:
        raise SearchError(f"could not connect: {e.reason}")
    except (TimeoutError, ValueError) as e:
        raise SearchError(str(e))


def search(query, fetch=_get_json):
    """Returns {"title", "url", "text"} for the best Wikipedia match."""
    query = (query or "").strip()[:200]
    if not query:
        raise SearchError("empty query")
    params = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": query,
                                     "srlimit": 1, "format": "json"})
    res = fetch(f"{SEARCH_URL}?{params}")
    hits = (res.get("query") or {}).get("search") or []
    if not hits:
        raise SearchError("no results")
    title = hits[0]["title"]
    summ = fetch(SUMMARY_URL + urllib.parse.quote(title.replace(" ", "_"), safe=""))
    text = (summ.get("extract") or "").strip()[:1500]
    url = ((summ.get("content_urls") or {}).get("desktop") or {}).get("page") \
        or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
    return {"title": summ.get("title") or title, "url": url, "text": text}
