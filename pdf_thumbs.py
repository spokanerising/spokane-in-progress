"""Page thumbnails for design documents (polish round, phase E).

For each project whose sheet row links a PDF (doc_url) and has image
permission on file (image_permission "granted" or "public-record", the same
rule as photos), the build downloads the PDF, draws its first page as a
600 px wide JPEG at p/<id>/doc-<fingerprint>.jpg, and counts its pages. The
project gets docThumb ("/p/<id>/doc-….jpg") and docPages; the project page
shows the thumbnail beside the link. Without permission the link still shows,
with no thumbnail.

Fails soft: no poppler (pdftoppm, pdfinfo), a download that fails or a file
that isn't a PDF just means no thumbnail (an earlier one is kept if the link
hasn't changed). A thumbnail is redrawn when the PDF's bytes change, checked
at most every 30 days. Notes in data/doc-thumbs.json.

    python3 pdf_thumbs.py   # nothing to run by hand; build.py calls add()
"""
import hashlib, json, os, shutil, subprocess, tempfile, urllib.request
from datetime import datetime, timedelta, timezone

CACHE = os.path.join("data", "doc-thumbs.json")
RECHECK = timedelta(days=30)
MAX_BYTES = 40 * 1024 * 1024
WIDTH = 600


def _load(root):
    try:
        return json.load(open(os.path.join(root, CACHE)))
    except (OSError, ValueError):
        return {}


def _save(root, cache):
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(root, CACHE), "w") as f:
        json.dump(cache, f, indent=2, sort_keys=True)


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "SpokaneInProgress/1.0 (+https://projects.spokanerising.com)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("larger than 40 MB")
    if not data.startswith(b"%PDF"):
        raise ValueError("not a PDF")
    return data


def _render(pdf_bytes, out_path):
    """First page → JPEG at out_path; returns the page count."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "doc.pdf")
        open(src, "wb").write(pdf_bytes)
        info = subprocess.run(["pdfinfo", src], capture_output=True, text=True, timeout=60)
        pages = next((int(line.split(":", 1)[1]) for line in info.stdout.splitlines() if line.startswith("Pages:")), 0)
        subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to-x", str(WIDTH), "-scale-to-y", "-1",
                        "-jpeg", "-jpegopt", "quality=82", src, os.path.join(tmp, "page")],
                       check=True, capture_output=True, timeout=120)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        shutil.move(os.path.join(tmp, "page.jpg"), out_path)
    return pages


def add(projects, root=".", now=None, fetch=_fetch):
    """Sets docThumb/docPages where a thumbnail exists. Removes the internal
    _docThumbOk flag from every project. Returns warnings."""
    now = now or datetime.now(timezone.utc)
    cache = _load(root)
    warnings = []
    have_poppler = bool(shutil.which("pdftoppm") and shutil.which("pdfinfo"))
    for p in projects:
        ok = p.pop("_docThumbOk", False)
        url = p.get("docUrl") or ""
        folder = os.path.join(root, "p", p["id"])
        old = cache.get(p["id"])
        if not (ok and url):
            continue
        fresh = old and old.get("url") == url and os.path.exists(os.path.join(root, old["file"].lstrip("/")))
        due = not fresh or now - datetime.fromisoformat(old["checked"]) > RECHECK
        if due and have_poppler:
            try:
                data = fetch(url)
                sha = hashlib.sha1(data).hexdigest()
                if not (fresh and old.get("sha") == sha):
                    rel = f"/p/{p['id']}/doc-{sha[:8]}.jpg"
                    pages = _render(data, os.path.join(root, rel.lstrip("/")))
                    if old and old.get("file") != rel:
                        try:
                            os.remove(os.path.join(root, old["file"].lstrip("/")))
                        except OSError:
                            pass
                    old = {"url": url, "sha": sha, "file": rel, "pages": pages}
                old["checked"] = now.isoformat()
                cache[p["id"]] = old
                fresh = True
            except Exception as error:   # fail soft: keep any earlier thumbnail
                warnings.append(f'{p["name"]}: no thumbnail for its PDF ({error}).')
        elif due and not have_poppler and not fresh:
            warnings.append(f'{p["name"]}: no thumbnail for its PDF (poppler is not installed).')
        if fresh and old:
            p["docThumb"] = old["file"]
            if old.get("pages"):
                p["docPages"] = old["pages"]
    _save(root, cache)
    return warnings
