#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from dotenv import load_dotenv
import openai
import pytz

# --------------------------------------------------
# 1) .env を読み込む
# --------------------------------------------------
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SAVE_DIR       = os.getenv("SAVE_DIR")
NICKNAME       = os.getenv("NICKNAME")
PROFILE        = os.getenv("PROFILE")

AI_FEEDS       = [u.strip() for u in os.getenv("AI_FEEDS", "").split(",") if u.strip()]
CRYPTO_FEEDS   = [u.strip() for u in os.getenv("CRYPTO_FEEDS", "").split(",") if u.strip()]

if not all([OPENAI_API_KEY, SAVE_DIR, NICKNAME, PROFILE]):
    raise ValueError("必要な環境変数が .env に設定されていません。")

client = openai.OpenAI(api_key=OPENAI_API_KEY)
os.makedirs(SAVE_DIR, exist_ok=True)

KEYWORDS_AI     = ["ai", "人工知能", "生成ai", "chatgpt", "gpt", "openai"]
KEYWORDS_CRYPTO = ["仮想通貨", "暗号資産", "ビットコイン", "ブロックチェーン", "crypto"]

# JSTの昨日〜今日の範囲を求める
jst = pytz.timezone("Asia/Tokyo")
now = datetime.now(jst)
today = now.date()
yesterday = today - timedelta(days=1)

def is_recent(published_str):
    try:
        dt = datetime.strptime(published_str, "%a, %d %b %Y %H:%M:%S %z")
        dt_jst = dt.astimezone(jst)
        return yesterday <= dt_jst.date() <= today
    except Exception:
        return False

def fetch_feed(feed_urls, keywords):
    results = []
    for url in feed_urls:
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            title = entry.title.lower()
            summary = getattr(entry, "summary", "").lower()
            published = getattr(entry, "published", "")
            if any(k in title or k in summary for k in keywords):
                if is_recent(published):
                    results.append({
                        "title": entry.title,
                        "url": entry.link,
                        "published": published
                    })
    return results[:5]

def fetch_text(url):
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n".join(paragraphs)[:2000]
    except Exception as e:
        return f"(本文取得失敗: {e})"

def gpt_summary(text):
    prompt = f"以下のニュース記事を日本語で200字以内に要約してください：\n{text}"
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.7,
    )
    return res.choices[0].message.content.strip()

def gpt_suggestion(summary):
    prompt = (
        f"以下のニュース要約に対して、{PROFILE} に向けた具体的な行動提案を"
        "3つリスト形式で出してください。\n"
        "発信、副業、コンテンツ化、収益化などにつながる、実行可能で少し挑戦的な内容にしてください。\n\n"
        f"{summary}"
    )
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.8,
    )
    return res.choices[0].message.content.strip()

def tag_from_suggestion(suggestion):
    s = suggestion.lower()
    tags = set()
    if "ai" in s or "人工知能" in s: tags.add("#AI")
    if any(k in s for k in ["仮想通貨", "ビットコイン", "暗号資産"]): tags.add("#仮想通貨")
    tags.update({"#副業", "#収益化案"})
    if "note"      in s: tags.add("#note案")
    if "twitter"   in s or "xで" in s or "ポスト" in s: tags.add("#X案")
    if "youtube"   in s: tags.add("#YouTube案")
    if "kindle"    in s: tags.add("#Kindle案")
    if "udemy"     in s: tags.add("#Udemy案")
    if "stand.fm"  in s or "音声配信" in s: tags.add("#音声配信案")
    return " ".join(sorted(tags))

def process_articles(articles, header):
    section = [f"## {header}\n"]
    for idx, art in enumerate(articles, 1):
        text       = fetch_text(art["url"])
        summary    = gpt_summary(text)
        suggestion = gpt_suggestion(summary)
        tags       = tag_from_suggestion(suggestion)

        section.append(f"### 〔{idx}〕 {art['title']}")
        section.append(f"- **公開日:** {art['published']}")
        section.append(f"- **URL:** {art['url']}\n")
        section.append(f"**要約:** {summary}\n")
        section.append(f"**{NICKNAME}への提案:**\n{suggestion}\n")
        section.append(f"{tags}\n")
    return section

def main():
    ai_articles = fetch_feed(AI_FEEDS, KEYWORDS_AI)
    crypto_articles = fetch_feed(CRYPTO_FEEDS, KEYWORDS_CRYPTO)

    filename = f"news_{now.strftime('%Y%m%d')}.md"
    content = [f"# {now.strftime('%Y-%m-%d')} の AI・仮想通貨ニュースまとめ\n"]
    content += process_articles(ai_articles, "🔷 AIニュース")
    content += process_articles(crypto_articles, "🔶 仮想通貨ニュース")

    with open(os.path.join(SAVE_DIR, filename), "w", encoding="utf-8") as f:
        f.write("\n".join(content))

    print(f"✅ 保存完了: {filename}")

if __name__ == "__main__":
    main()

