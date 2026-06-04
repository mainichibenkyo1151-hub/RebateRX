import os
import json
import feedparser
from datetime import datetime
import requests  # Replaced deepl with requests for the AI API

# =========================
# RSS SOURCES
# =========================

RSS_FEEDS = [
    "https://www.fiercepharma.com/rss/xml",
    "https://www.drugchannels.net/feeds/posts/default",
    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds",
    "https://www.cms.gov/newsroom/rss-feeds",
    "https://www.ftc.gov/feeds/press-releases/rss"
]

# =========================
# KEYWORD FILTER (pre-filter noise)
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
# FETCH RSS
# =========================

def fetch_feed(url):
    try:
        feed = feedparser.parse(url)

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
    for url in RSS_FEEDS:
        all_items.extend(fetch_feed(url))
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
# RELEVANCE SCORING ENGINE
# =========================

def score_article(text):
    t = text.lower()
    score = 0

    # High-impact regulatory signals
    if "fda" in t: score += 25
    if "approval" in t: score += 20
    if "recall" in t: score += 30
    if "shortage" in t: score += 25
    if "drug shortage" in t: score += 35

    # Core RebateRX signals (highest weight)
    if "pbm" in t: score += 40
    if "rebate" in t: score += 30
    if "medicare" in t: score += 30
    if "medicaid" in t: score += 20
    if "formulary" in t: score += 30
    if "prior authorization" in t: score += 35
    if "copay" in t: score += 20

    # Drug categories
    if "insulin" in t: score += 25
    if "glp-1" in t or "ozempic" in t or "wegovy" in t:
        score += 30

    # Policy signals
    if "policy" in t: score += 15
    if "law" in t or "bill" in t: score += 10
    if "announc" in t: score += 10

    # Penalties for noise
    if "press release" in t: score -= 10
    if "sponsored" in t: score -= 50

    return score


def enrich_with_scores(items):
    for i in items:
        text = i["title"] + " " + i["summary"]
        i["score"] = score_article(text)
    return items


# =========================
# CATEGORIZATION
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
# RANKING (Bloomberg-style ordering)
# =========================

def rank_items(items):
    return sorted(items, key=lambda x: x["score"], reverse=True)


# =========================
# TRANSFORM TO FINAL JSON
# =========================

def transform(items):
    results = []

    for i in items:
        text = i["title"] + " " + i["summary"]

        results.append({
            "id": i["link"],

            "headline": translate_fields(i["title"]),

            "summary": {
                lang: translate_text(i["summary"][:300], lang_name)
                for lang, lang_name in LANG_MAP.items()
            },

            "category": categorize(text),
            "score": i["score"],
            "patientImpact": {
                lang: translate_text(
                    "May affect drug access, coverage, or cost.",
                    lang_name
                )
                for lang, lang_name in LANG_MAP.items()
            },

            "link": i["link"],
            "published": i["published"]
        })

    return results


# =========================
# BUILD PIPELINE
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
    os.system("git add news.json")
    os.system('git commit -m "update pharma news feed" || exit 0')
    os.system("git push")

# =========================
# TRANSLATION ENGINE (Meta Llama-3 via OpenRouter API Key)
# =========================

# Maps language keys to full names for the AI's prompt context
LANG_MAP = {
    "en": "English",
    "es": "Spanish",
    "zh": "Simplified Chinese",
    "vi": "Vietnamese",
    "ja": "Japanese"
}

# Pull your OpenRouter token securely from environment variables
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

def translate_text(text, target_language):
    if not text:
        return ""

    if target_language == "English":
        return text

    # Guard clause if the GitHub Actions environment secret is missing
    if not OPENROUTER_API_KEY:
        print("Warning: OPENROUTER_API_KEY not found. Falling back to English.")
        return text

    url = "https://openrouter.ai"
    
    prompt = (
        f"You are an expert pharmaceutical and healthcare translator.\n"
        f"Translate the following text into fluent, natural {target_language}.\n"
        f"Ensure specialized US healthcare terms like PBM, formulary, copay, 340B, "
        f"and rebates are translated into their correct professional industry equivalents.\n"
        f"Return ONLY the final translated text. Do not include intros, notes, explanations, or quotes.\n\n"
        f"Text to translate: {text}"
    )

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "HTTP-Referer": "https://github.com",
                "X-Title": "Pharma RSS Translator"
            },
            json={
                "model": "meta-llama/llama-3-8b-instruct:free",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1  # Low temperature makes the output deterministic and clean
            },
            timeout=15
        )
        
        result = response.json()
        
        # Handle cases where OpenRouter returns an API error payload
        if 'choices' not in result:
            print(f"OpenRouter Error for {target_language}: {result.get('error', 'Unknown Error')}")
            return text
            
        translated_output = result['choices']['message']['content'].strip()
        return translated_output

    except Exception as e:
        print(f"Llama-3 translation failed for language '{target_language}': {e}")
        return text  # Safe fallback to English text string if API drops
        

def translate_fields(text):
    return {
        lang: translate_text(text, lang_name)
        for lang, lang_name in LANG_MAP.items()
    }

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
