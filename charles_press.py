#!/usr/bin/env python3
"""
Charles Press — Lit le flux Google Alerts dédié aux mentions de Charles
(retombées presse). Extrait titre, auteur, média, date, et sauvegarde
dans new_press.json pour revue manuelle avant ajout dans PRESS.md.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

RSS_FEEDS = [
    # Alerte "Charles" (retombées presse sur l'extension)
    "https://www.google.com/alerts/feeds/10527137650121336393/2557627484399113078",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

SCRIPT_DIR = Path(__file__).parent
PROCESSED_FILE = SCRIPT_DIR / "processed_press.json"
NEW_PRESS_FILE = SCRIPT_DIR / "new_press.json"


def load_processed():
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return []


def is_processed(url, processed):
    return any(a["url"] == url for a in processed)


def get_source(url):
    """Extrait le nom du média à partir du domaine."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def fetch_rss():
    articles = []
    for feed_url in RSS_FEEDS:
        print(f"📡 {feed_url[:80]}...")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                url = entry.get("link", "")
                if "google.com/url" in url:
                    match = re.search(r"url=([^&]+)", url)
                    if match:
                        url = requests.utils.unquote(match.group(1))
                title = BeautifulSoup(entry.get("title", ""), "html.parser").get_text()
                published = entry.get("published", "") or entry.get("updated", "")
                articles.append({"title": title, "url": url, "feed_published": published})
        except Exception as e:
            print(f"   ⚠ Erreur : {e}")
    seen = set()
    unique = []
    for a in articles:
        if a["url"] not in seen:
            seen.add(a["url"])
            unique.append(a)
    return unique


def extract_article(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        author = None
        for meta in soup.find_all("meta"):
            name = (meta.get("name") or "").lower()
            prop = (meta.get("property") or "").lower()
            if name in ("author", "article:author") or prop in ("author", "article:author"):
                author = meta.get("content", "").strip()
                break
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0]
                if "author" in data:
                    a = data["author"]
                    if isinstance(a, list):
                        a = a[0]
                    if isinstance(a, dict):
                        author = a.get("name", author)
                    elif isinstance(a, str):
                        author = a

                if "datePublished" in data:
                    published = data["datePublished"]
                else:
                    published = None
            except Exception:
                published = None

        published = None
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or "").lower()
            name = (meta.get("name") or "").lower()
            if prop in ("article:published_time", "og:published_time") or name in ("date", "pubdate", "publishdate"):
                published = meta.get("content", "").strip()
                break

        site_name = None
        for meta in soup.find_all("meta"):
            prop = (meta.get("property") or "").lower()
            if prop == "og:site_name":
                site_name = meta.get("content", "").strip()
                break

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        mentions_charles = "charles" in text.lower()

        return {
            "author": author,
            "published": published,
            "site_name": site_name,
            "mentions_charles": mentions_charles,
            "content": text[:3000],
        }
    except Exception as e:
        return {
            "author": None,
            "published": None,
            "site_name": None,
            "mentions_charles": False,
            "content": None,
            "error": str(e),
        }


def main():
    print("📰 Charles Press — Suivi des retombées\n")

    processed = load_processed()
    print(f"📋 {len(processed)} retombées déjà traitées")

    articles = fetch_rss()
    print(f"\n📰 {len(articles)} articles dans le flux")

    new = [a for a in articles if not is_processed(a["url"], processed)]
    print(f"🆕 {len(new)} nouvelles retombées\n")

    if not new:
        print("Rien de nouveau.")
        return

    results = []
    for i, article in enumerate(new, 1):
        print(f"[{i}/{len(new)}] {article['title'][:60]}...")
        info = extract_article(article["url"])

        source = info.get("site_name") or get_source(article["url"])
        author = info.get("author")
        published = info.get("published") or article.get("feed_published")
        flag = "✅" if info.get("mentions_charles") else "⚠ Charles non mentionné"

        print(f"    📍 {source} | 👤 {author or '?'} | 📅 {published or '?'} | {flag}")

        results.append({
            "title": article["title"],
            "url": article["url"],
            "source": source,
            "author": author,
            "published": published,
            "mentions_charles": info.get("mentions_charles"),
            "content": info.get("content"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    NEW_PRESS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    confirmed = sum(1 for r in results if r["mentions_charles"])
    print(f"\n✅ {len(results)} retombées sauvegardées dans new_press.json")
    print(f"   ✅ {confirmed} mentionnent Charles, ⚠ {len(results) - confirmed} à vérifier")
    print(f"\n👉 Revue manuelle puis ajout dans PRESS.md")
    print(f"👉 Une fois traité, ajouter les URLs à processed_press.json")


if __name__ == "__main__":
    main()
