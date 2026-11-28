"""One-off outside-link check for issue #41 (run on GitHub, which can reach
the city's and county's sites). Prints one line per link: status, the URL,
where it ended up, and the page title, so 'page not found' pages that answer
200 can be spotted too."""
import json, re, sys, urllib.request, concurrent.futures as cf, ssl
links = json.load(open(sys.argv[1]))
UA = {"User-Agent": "Mozilla/5.0 (link check for projects.spokanerising.com)"}
def check(url):
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(200000).decode("utf-8", "replace")
            title = re.search(r"<title[^>]*>(.*?)</title>", body, re.S | re.I)
            title = re.sub(r"\s+", " ", title.group(1)).strip()[:80] if title else ""
            flags = [w for w in ("not found", "no records", "error", "invalid", "does not exist", "no matching")
                     if w in body.lower()]
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)))
            i = text.lower().find("no record")
            snip = text[max(0, i - 150): i + 150] if i >= 0 else text[:300]
            return r.status, url, r.geturl() if r.geturl() != url else "", title, ",".join(flags), snip
    except urllib.error.HTTPError as e:
        return e.code, url, "", "", ""
    except Exception as e:
        return "ERR", url, "", str(e)[:80], ""
with cf.ThreadPoolExecutor(6) as pool:
    for res in pool.map(check, links):
        print("LINK\t" + "\t".join(str(x) for x in res), flush=True)
