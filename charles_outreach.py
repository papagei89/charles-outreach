#!/usr/bin/env python3
"""
Charles Outreach — Lit les flux RSS Google Alerts,
récupère le contenu des articles et identifie les journalistes.
Sauvegarde les résultats dans new_articles.json pour traitement.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from bs4 import BeautifulSoup

RSS_FEEDS = [
    # FR
    "https://www.google.fr/alerts/feeds/10527137650121336393/9177345942886177832",
    "https://www.google.fr/alerts/feeds/10527137650121336393/14078392464878489534",
    "https://www.google.fr/alerts/feeds/10527137650121336393/4197579771038252840",
    "https://www.google.fr/alerts/feeds/10527137650121336393/4502141300537586919",
    # DE
    "https://www.google.com/alerts/feeds/10527137650121336393/2062644191746562873",
    "https://www.google.com/alerts/feeds/10527137650121336393/17349187502244847551",
]

SKIP_DOMAINS = ["linkedin.com", "facebook.com", "twitter.com", "x.com"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

SCRIPT_DIR = Path(__file__).parent
PROCESSED_FILE = SCRIPT_DIR / "processed_articles.json"
NEW_ARTICLES_FILE = SCRIPT_DIR / "new_articles.json"


def load_processed():
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return []


def is_processed(url, processed):
    return any(a["url"] == url for a in processed)


def should_skip(url):
    return any(domain in url for domain in SKIP_DOMAINS)


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
                articles.append({"title": title, "url": url})
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

        # Auteur
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
            except Exception:
                pass

        # Email
        generic = ["contact@", "info@", "admin@", "support@", "noreply@", "no-reply@", "privacy@", "legal@", "webmaster@", "redaction@"]
        emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', resp.text)
        journalist_email = next((e for e in emails if not any(e.lower().startswith(g) for g in generic)), None)

        # Contenu
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        return {
            "author": author,
            "email": journalist_email,
            "content": text[:3000],
        }
    except Exception as e:
        return {"author": None, "email": None, "content": None, "error": str(e)}


def main():
    print("🚀 Charles Outreach — Lecture RSS\n")

    processed = load_processed()
    print(f"📋 {len(processed)} articles déjà traités")

    articles = fetch_rss()
    print(f"\n📰 {len(articles)} articles dans les flux")

    new = [a for a in articles if not is_processed(a["url"], processed) and not should_skip(a["url"])]
    print(f"🆕 {len(new)} nouveaux articles\n")

    if not new:
        print("Rien de nouveau.")
        return

    results = []
    for i, article in enumerate(new, 1):
        print(f"[{i}/{len(new)}] {article['title'][:60]}...")
        info = extract_article(article["url"])
        results.append({
            "title": article["title"],
            "url": article["url"],
            "author": info.get("author"),
            "email": info.get("email"),
            "content": info.get("content"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    NEW_ARTICLES_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\n✅ {len(results)} articles sauvegardés dans new_articles.json")


if __name__ == "__main__":
    main()
