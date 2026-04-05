#!/usr/bin/env python3
"""
Charles Outreach — Lit les flux RSS Google Alerts,
récupère le contenu des articles et identifie les journalistes.
Utilise Hunter.io pour trouver les emails.
Sauvegarde les résultats dans new_articles.json pour traitement.
"""

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

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
    # EU languages — "souveraineté/soberanía/sovranità digitale" etc.
    "https://www.google.com/alerts/feeds/10527137650121336393/12842318564863564242",
    "https://www.google.com/alerts/feeds/10527137650121336393/4436570368563472065",
    "https://www.google.com/alerts/feeds/10527137650121336393/8638822799439434197",
    "https://www.google.com/alerts/feeds/10527137650121336393/8638822799439436678",
    "https://www.google.com/alerts/feeds/10527137650121336393/8077719845921761635",
    "https://www.google.com/alerts/feeds/10527137650121336393/16978861947408862996",
    "https://www.google.com/alerts/feeds/10527137650121336393/16978861947408860074",
    "https://www.google.com/alerts/feeds/10527137650121336393/2487475033548909777",
    "https://www.google.com/alerts/feeds/10527137650121336393/7687914229791810053",
    "https://www.google.com/alerts/feeds/10527137650121336393/7687914229791810225",
    "https://www.google.com/alerts/feeds/10527137650121336393/1465575245791626263",
    "https://www.google.com/alerts/feeds/10527137650121336393/18201389133253053999",
    "https://www.google.com/alerts/feeds/10527137650121336393/8201337302746870789",
    "https://www.google.com/alerts/feeds/10527137650121336393/4520455992978468954",
    "https://www.google.com/alerts/feeds/10527137650121336393/2900238083522821305",
    "https://www.google.com/alerts/feeds/10527137650121336393/8097810763828790472",
    "https://www.google.com/alerts/feeds/10527137650121336393/8097810763828790830",
    "https://www.google.com/alerts/feeds/10527137650121336393/9453177869860021272",
    "https://www.google.com/alerts/feeds/10527137650121336393/9453177869860023944",
]

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")

SKIP_DOMAINS = ["linkedin.com", "facebook.com", "twitter.com", "x.com"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

SCRIPT_DIR = Path(__file__).parent
PROCESSED_FILE = SCRIPT_DIR / "processed_articles.json"
NEW_ARTICLES_FILE = SCRIPT_DIR / "new_articles.json"

# Cache des formats Hunter par domaine (pour ne pas gaspiller les requêtes)
_hunter_cache = {}


def load_processed():
    if PROCESSED_FILE.exists():
        return json.loads(PROCESSED_FILE.read_text())
    return []


def is_processed(url, processed):
    return any(a["url"] == url for a in processed)


def should_skip(url):
    return any(domain in url for domain in SKIP_DOMAINS)


def normalize_name(name):
    """Retire les accents et met en minuscule."""
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def get_domain(url):
    """Extrait le domaine principal d'une URL."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def hunter_find_email(domain, author_name):
    """Utilise Hunter.io pour trouver l'email d'un journaliste."""
    if not HUNTER_API_KEY or not author_name or not domain:
        return None, None

    # Séparer prénom/nom
    parts = author_name.strip().split()
    if len(parts) < 2:
        return None, None

    first_name = parts[0]
    last_name = parts[-1]

    # Vérifier le cache
    cache_key = f"{domain}:{normalize_name(first_name)}:{normalize_name(last_name)}"
    if cache_key in _hunter_cache:
        return _hunter_cache[cache_key]

    # API email-finder
    try:
        resp = requests.get(
            "https://api.hunter.io/v2/email-finder",
            params={
                "domain": domain,
                "first_name": first_name,
                "last_name": last_name,
                "api_key": HUNTER_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            email = data.get("email")
            score = data.get("score")
            if email and score and score >= 50:
                result = (email, score)
                _hunter_cache[cache_key] = result
                return result
    except Exception as e:
        print(f"      ⚠ Hunter erreur : {e}")

    _hunter_cache[cache_key] = (None, None)
    return None, None


def hunter_domain_search(domain):
    """Cherche les emails connus pour un domaine via Hunter.io."""
    if not HUNTER_API_KEY or not domain:
        return []

    if domain in _hunter_cache:
        return _hunter_cache[domain]

    try:
        resp = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": 5},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            emails = data.get("emails", [])
            pattern = data.get("pattern")
            result = {"pattern": pattern, "emails": emails}
            _hunter_cache[domain] = result
            return result
    except Exception:
        pass

    _hunter_cache[domain] = {"pattern": None, "emails": []}
    return _hunter_cache[domain]


def guess_email(domain, author_name):
    """Devine l'email à partir du format du domaine et du nom."""
    if not author_name or not domain:
        return None

    parts = author_name.strip().split()
    if len(parts) < 2:
        return None

    first = normalize_name(parts[0])
    last = normalize_name(parts[-1])

    # Patterns courants
    guesses = [
        f"{first}.{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}@{domain}",
        f"{first[0]}.{last}@{domain}",
        f"{last}.{first}@{domain}",
    ]

    # Si Hunter a trouvé le pattern du domaine, l'utiliser en priorité
    domain_info = hunter_domain_search(domain)
    pattern = domain_info.get("pattern") if isinstance(domain_info, dict) else None

    if pattern:
        email = pattern.replace("{first}", first).replace("{last}", last).replace("{f}", first[0])
        email = f"{email}@{domain}" if "@" not in email else email
        return email

    # Sinon retourner le plus courant
    return guesses[0]


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

        # Email dans la page
        generic = [
            "contact@", "info@", "admin@", "support@", "noreply@",
            "no-reply@", "privacy@", "legal@", "webmaster@", "redaction@",
        ]
        emails_in_page = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', resp.text)
        # Filtrer le bruit (fichiers, placeholders, etc.)
        valid_emails = [
            e for e in emails_in_page
            if not any(e.lower().startswith(g) for g in generic)
            and not any(e.endswith(ext) for ext in [".jpg", ".png", ".js", ".css", ".svg"])
            and "@" in e
            and "exemple" not in e.lower()
            and "example" not in e.lower()
            and "organisation" not in e.lower()
            and "naam" not in e.lower()
        ]
        page_email = valid_emails[0] if valid_emails else None

        # Contenu
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)

        return {
            "author": author,
            "page_email": page_email,
            "content": text[:3000],
        }
    except Exception as e:
        return {"author": None, "page_email": None, "content": None, "error": str(e)}


def find_email(url, author, page_email):
    """Stratégie en 3 étapes pour trouver l'email."""
    domain = get_domain(url)

    # 1. Email trouvé dans la page (si ça ressemble à un vrai email)
    if page_email and len(page_email) > 5:
        return page_email, "page"

    # 2. Hunter.io email-finder
    if author and domain:
        hunter_email, score = hunter_find_email(domain, author)
        if hunter_email:
            return hunter_email, f"hunter ({score}%)"

    # 3. Devinette basée sur le pattern du domaine
    if author and domain:
        guessed = guess_email(domain, author)
        if guessed:
            return guessed, "guess"

    return None, None


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

        author = info.get("author")
        page_email = info.get("page_email")

        email, source = find_email(article["url"], author, page_email)

        if email:
            print(f"    👤 {author or '?'} → 📧 {email} ({source})")
        else:
            print(f"    👤 {author or '?'} → ❌ pas d'email")

        results.append({
            "title": article["title"],
            "url": article["url"],
            "author": author,
            "email": email,
            "email_source": source,
            "content": info.get("content"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    NEW_ARTICLES_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))

    with_email = sum(1 for r in results if r["email"])
    print(f"\n✅ {len(results)} articles sauvegardés dans new_articles.json")
    print(f"   📧 {with_email} avec email, ❌ {len(results) - with_email} sans")


if __name__ == "__main__":
    main()
