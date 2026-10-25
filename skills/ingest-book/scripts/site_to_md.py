#!/usr/bin/env python3
"""
site_to_md.py - mirror a website's articles into Markdown for the library (e.g. less.works, orgtopologies.com).

  python3 site_to_md.py https://less.works --out library/sites/less-works [--include /less/ --max 400 --delay 1.0]

Reads sitemap.xml (and nested sitemaps), keeps URLs matching --include prefixes, fetches each page politely
(robots.txt respected, delay between requests), keeps the main content (<main>/<article>, else <body> minus
nav/header/footer/script) and writes pages/<path-slug>.md with frontmatter {title, url, fetched}.
Images become text placeholders  [IMAGE: alt-text | src]  so a later pass can describe the important ones.
Writes index.md (status: converted) so build_library_index.py picks the site up.

Personal use only: keep the output in a private repository; do not republish.
Requires: requests, beautifulsoup4, markdownify
"""
import argparse, datetime, json, re, time, urllib.robotparser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify

UA = "personal-library-mirror/1.0 (+private use)"


def sitemap_urls(base, session):
    todo, seen, urls = [urljoin(base, "/sitemap.xml")], set(), []
    while todo:
        sm = todo.pop()
        if sm in seen:
            continue
        seen.add(sm)
        r = session.get(sm, timeout=30)
        if r.status_code != 200:
            continue
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", r.text)
        if "<sitemapindex" in r.text:
            todo.extend(locs)
        else:
            urls.extend(locs)
    return list(dict.fromkeys(urls))


def page_to_md(html, url):
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.find("h1") or soup.title or soup.new_tag("x")).get_text(" ", strip=True)
    root = soup.find("main") or soup.find("article") or soup.body or soup
    for t in root.find_all(["nav", "header", "footer", "script", "style", "noscript", "form", "iframe"]):
        t.decompose()
    for img in root.find_all("img"):
        alt = img.get("alt", "").strip() or "no alt text"
        img.replace_with(f" [IMAGE: {alt} | {urljoin(url, img.get('src', ''))}] ")
    md = markdownify(str(root), heading_style="ATX", bullets="-")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return title, md


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base")
    ap.add_argument("--out", required=True)
    ap.add_argument("--include", action="append", default=[], help="URL path prefix to keep (repeatable)")
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--delay", type=float, default=1.0)
    a = ap.parse_args()
    out = Path(a.out); (out / "pages").mkdir(parents=True, exist_ok=True)
    s = requests.Session(); s.headers["User-Agent"] = UA
    rp = urllib.robotparser.RobotFileParser(urljoin(a.base, "/robots.txt")); rp.read()
    host = urlparse(a.base).netloc
    urls = [u for u in sitemap_urls(a.base, s) if urlparse(u).netloc == host
            and (not a.include or any(urlparse(u).path.startswith(p) for p in a.include))][:a.max]
    rows, words = [], 0
    for u in urls:
        if not rp.can_fetch(UA, u):
            continue
        r = s.get(u, timeout=30)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        title, md = page_to_md(r.text, u)
        slug = re.sub(r"[^a-z0-9]+", "-", urlparse(u).path.lower()).strip("-") or "home"
        fm = {"title": title, "url": u, "fetched": datetime.date.today().isoformat()}
        (out / "pages" / f"{slug}.md").write_text(
            "---\n" + "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in fm.items())
            + f"\n---\n\n> Source: {u}\n\n{md}\n", encoding="utf-8")
        rows.append((title, slug, u)); words += len(md.split())
        time.sleep(a.delay)
    idx = ["---", f"title: {json.dumps(host)}", f"author: {json.dumps(host)}", "year: null",
           f"words: {words}", f"pages: {len(rows)}", f"ingested: {datetime.date.today().isoformat()}",
           "status: converted", "---", "", f"# {host}", "", "| Page | URL |", "|---|---|"]
    idx += [f"| [{t}](pages/{sl}.md) | {u} |" for t, sl, u in rows]
    (out / "index.md").write_text("\n".join(idx) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(rows), "words": words, "out": str(out)}))


if __name__ == "__main__":
    main()
