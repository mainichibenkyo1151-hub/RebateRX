import os
import json
import feedparser
from datetime import datetime
import requests
import re

# =========================
# RSS SOURCES
# =========================

RSS_FEEDS = [
    "https://www.fiercepharma.com/rss.xml",
    "https://www.drugchannels.net/feeds/posts/default?alt=rss",
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/rss-feed-recent-press-announcements",
    "https://www.cms.gov/newsroom/rss-feeds/press-releases.xml",
    "https://www.ftc.gov/feeds/press-releases.xml"
]

# =========================
# KEYWORDS (pre-filter noise)
# =========================

KEYWORDS = [
    "drug", "price", "pricing", "rebate", "pbm", "formulary",
    "medicare", "medicaid", "copay", "biosimilar",
    "fda", "approval", "shortage", "pharmacy",
    "insulin", "glp-1", "ozempic", "wegovy",
    "prior authorization", "coverage", "reimbursement",
    "drug shortage", "generic", "specialty pharmacy"
]

# =========================
# LANGUAGE CONFIG
# =========================

LANG_MAP = {
    "en": "English",
    "es": "Spanish",
    "zh": "Simplified Chinese",
    "vi": "Vietnamese",
    "ja": "Japanese"
}

# =========================
# TRANSLATION ENGINE (GeneralTranslation.com)
# =========================

GT_API_KEY = os.getenv("GENERALTRANSLATION_API_KEY")
print("API Key Found:", GT_API_KEY is not None)
GT_ENDPOINT = "https://api.generaltranslation.com/v1/translate"


def translate_text(text, target_language):
    """
    Translate text using GeneralTranslation.com.
    Falls back to English if API fails.
    """

    if not text:
        return ""

    if target_language == "English":
        return text

    if not GT_API_KEY:
        print("WARNING: Missing GENERALTRANSLATION_API_KEY. Falling back to English.")
        return text

    payload = {
        "text": text,
        "target_language": target_language,
        "source_language": "English",
        "domain": "medical_pharma"
    }

    headers = {
        "Authorization": f"Bearer {GT_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(
            GT_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=15
        )

        print(f"Translation status: {response.status_code}")

        if response.status_code != 200:
            print(response.text)
            return text

        data = response.json()

        print("Translation response:")
        print(json.dumps(data, indent=2))

        return data.get("translated_text", text).strip()

    except Exception as e:
        print(f"Translation failed: {e}")
        return text


def translate_fields(text):
    return {
        lang: translate_text(text, lang_name)
        for lang, lang_name in LANG_MAP.items()
    }


# =========================
# FETCH RSS
# =========================

def fetch_feed(url):
    try:
        feed = feedparser.parse(url)

        if not hasattr(feed, "entries") or len(feed.entries) == 0:
            print(f"[WARN] No entries found for: {url}")
            return []

        items = []
        for entry in feed.entries:
            items.append({
                "title": getattr(entry, "title", ""),
                "summary": getattr(entry, "summary", ""),
                "link": getattr(entry, "link", ""),
                "published": getattr(entry, "published", ""),
                "source": url
            })

        return items

    except Exception as e:
        print(f"Feed error ({url}): {e}")
        return []


def load_all():
    all_items = []
    failed_feeds = []

    print("Starting RSS ingestion...")

    for url in RSS_FEEDS:
        print(f"Fetching: {url}")

        items = fetch_feed(url)

        # Hard validation: detect broken feeds early
        if items is None:
            print(f"[ERROR] None returned from: {url}")
            failed_feeds.append(url)
            continue

        if len(items) == 0:
            print(f"[WARN] No items found in feed: {url}")
            failed_feeds.append(url)
            continue

        print(f"[OK] Retrieved {len(items)} items from {url}")
        all_items.extend(items)

    print("\n===== RSS SUMMARY =====")
    print(f"Total items loaded: {len(all_items)}")
    print(f"Failed feeds: {len(failed_feeds)}")

    if failed_feeds:
        print("Problem feeds:")
        for f in failed_feeds:
            print(f" - {f}")

    return all_items


# =========================
# FILTERING
# =========================

def is_relevant(text):
    text = text.lower()
    return any(k in text for k in KEYWORDS)


def filter_items(items):
    return [
        i for i in items
        if is_relevant(i["title"] + " " + i["summary"])
    ]


# =========================
# DEDUPLICATION
# =========================

def deduplicate(items):
    seen = set()
    unique = []

    for i in items:
        key = i["title"].strip().lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(i)

    return unique

# =========================
# CLEAN HTML
# =========================

def clean_html(text):
    if not text:
        return ""

    # remove HTML tags
    text = re.sub(r"<[^>]*>", " ", text)

    # collapse whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# =========================
# SCORING ENGINE
# =========================

def score_article(text):
    t = text.lower()
    score = 0

    if "fda" in t: score += 25
    if "approval" in t: score += 20
    if "recall" in t: score += 30
    if "shortage" in t: score += 25
    if "drug shortage" in t: score += 35

    if "pbm" in t: score += 40
    if "rebate" in t: score += 30
    if "medicare" in t: score += 30
    if "medicaid" in t: score += 20
    if "formulary" in t: score += 30
    if "prior authorization" in t: score += 35
    if "copay" in t: score += 20

    if "insulin" in t: score += 25
    if "glp-1" in t or "ozempic" in t or "wegovy" in t:
        score += 30

    if "policy" in t: score += 15
    if "law" in t or "bill" in t: score += 10
    if "announc" in t: score += 10

    if "press release" in t: score -= 10
    if "sponsored" in t: score -= 50

    return score


def enrich_with_scores(items):
    for i in items:
        text = i["title"] + " " + i["summary"]
        i["score"] = score_article(text)
    return items


# =========================
# CATEGORY ENGINE
# =========================

def categorize(text):
    t = text.lower()

    if "fda" in t or "approval" in t:
        return "FDA"
    if "pbm" in t or "rebate" in t:
        return "PBM"
    if "medicare" in t or "medicaid" in t:
        return "Insurance"
    if "shortage" in t:
        return "Shortage"
    if "price" in t or "pricing" in t:
        return "Pricing"
    if "copay" in t:
        return "Access"

    return "Pharma"


# =========================
# RANKING
# =========================

def rank_items(items):
    return sorted(items, key=lambda x: x["score"], reverse=True)

# =========================
# TRANSLATE BUNDLE
# =========================

def translate_bundle(text):
    return {
        lang: translate_text(text, lang_name)
        for lang, lang_name in LANG_MAP.items()
    }



# =========================
# TRANSFORM FINAL OUTPUT
# =========================

def transform(items):
    results = []

    for i in items:
        clean_summary = clean_html(i["summary"])[:300]

        title = i["title"]
        impact = "May affect drug access, coverage, or cost."

        results.append({
            "id": i["link"],

            "headline": translate_bundle(title),

            "summary": translate_bundle(clean_summary),

            "category": categorize(title + " " + clean_summary),

            "score": i["score"],

            "patientImpact": translate_bundle(impact),

            "link": i["link"],
            "published": i["published"]
        })

    return results


# =========================
# PIPELINE
# =========================

def build_news():
    raw = load_all()

    filtered = filter_items(raw)
    filtered = deduplicate(filtered)

    scored = enrich_with_scores(filtered)
    ranked = rank_items(scored)

    top = ranked[:25]

    return transform(top)


# =========================
# SAVE OUTPUT
# =========================

def save(news):
    output = {
        "generatedAt": datetime.utcnow().isoformat() + "Z",
        "count": len(news),
        "articles": news
    }

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


# =========================
# GIT PUSH
# =========================

def push_to_git():
    os.system("git config user.name 'github-actions'")
    os.system("git config user.email 'github-actions@github.com'")
    os.system("git add news.json")
    os.system('git commit -m "update pharma news feed" || exit 0')
    os.system("git push")


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    print("Fetching RSS feeds...")
    news = build_news()

    print(f"Top articles generated: {len(news)}")

    print("Saving news.json...")
    save(news)

    print("Pushing to GitHub...")
    push_to_git()

    print("Done.")
