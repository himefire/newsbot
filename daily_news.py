#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI／仮想通貨ニュースを自動要約して Obsidian に保存するスクリプト
個人情報・キー類は .env に置く前提（.gitignore に .env を入れておくこと）
"""

import os
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from dotenv import load_dotenv
import openai

# --------------------------------------------------
# 1) .env を読み込む
# --------------------------------------------------
load_dotenv()  # 同じフォルダの .env をロード

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")       # 必須
SAVE_DIR        = os.getenv("SAVE_DIR")            # 必須
NICKNAME        = os.getenv("NICKNAME")            # 必須
PROFILE         = os.getenv("PROFILE")             # 必須

# RSS フィードはカンマ区切りで複数指定可
AI_FEEDS = [u.strip() for u in os.getenv("AI_FEEDS", "").split(",") if u.strip()]
CRYPTO_FEEDS = os.getenv("CRYPTO_FEEDS", "").split(",")

if not all([OPENAI_API_KEY, SAVE_DIR, NICKNAME, PROFILE]):
    raise ValueError("必要な環境変数（OPENAI_API_KEY, SAVE_DIR, NICKNAME, PROFILE）が .env に設定されていません。")

# --------------------------------------------------
# 2) OpenAI クライアントの初期化
# --------------------------------------------------
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# --------------------------------------------------
# 3) 保存先ディレクトリの準備
# --------------------------------------------------
os.makedirs(SAVE_DIR, exist_ok=True)

# --------------------------------------------------
# 4) ニュース取得設定
# --------------------------------------------------
KEYWORDS_AI     = ["ai", "人工知能", "生成ai", "chatgpt", "gpt", "openai"]
KEYWORDS_CRYPTO = ["仮想通貨", "暗号資産", "ビットコイン", "ブロックチェーン", "crypto"]

# --------------------------------------------------
# 5) RSS 取得＆フィルタ
# --------------------------------------------------
def fetch_feed(feed_urls, keywords):
    """RSS フィードから最大 5 件の記事を取得"""
    results = []
    for url in filter(None, feed_urls):       # 空文字を除外
        url = url.strip()
        feed = feedparser.parse(url)
        for entry in feed.entries[:20]:
            title   = entry.title.lower()
            summary = getattr(entry, "summary", "").lower()
            if any(k in title or k in summary for k in keywords):
                results.append(
                    {
                        "title": entry.title,
                        "url":   entry.link,
                        "published": getattr(entry, "published", "不明")
                    }
                )
    # 新しい順に並び替え（published が無い場合はそのまま）
    results.sort(key=lambda x: x["published"], reverse=True)
    return results[:5]

# --------------------------------------------------
# 6) 本文スクレイピング（2000 文字上限）
# --------------------------------------------------
def fetch_text(url: str) -> str:
    try:
        res = requests.get(url, timeout=10)
        soup = BeautifulSoup(res.text, "html.parser")
        paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n".join(paragraphs)[:2000]
    except Exception as e:
        return f"(本文取得失敗: {e})"

# --------------------------------------------------
# 7) ChatGPT で要約
# --------------------------------------------------
def gpt_summary(text: str) -> str:
    prompt = f"以下のニュース記事を日本語で200字以内に要約してください：\n{text}"
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=300,
        temperature=0.7,
    )
    return res.choices[0].message.content.strip()

# --------------------------------------------------
# 8) ChatGPT で行動提案
# --------------------------------------------------
def gpt_suggestion(summary: str) -> str:
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

# --------------------------------------------------
# 9) タグ自動生成
# --------------------------------------------------
def tag_from_suggestion(suggestion: str) -> str:
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

# --------------------------------------------------
# 10) Markdown 生成
# --------------------------------------------------
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

# --------------------------------------------------
# 11) メイン処理
# --------------------------------------------------
def main():
    ai_articles     = fetch_feed(AI_FEEDS, KEYWORDS_AI)
    crypto_articles = fetch_feed(CRYPTO_FEEDS, KEYWORDS_CRYPTO)

    today    = datetime.now().strftime("%Y-%m-%d")
    filename = f"news_{datetime.now():%Y%m%d}.md"

    content = [f"# {today} の AI・仮想通貨ニュースまとめ\n"]
    content += process_articles(ai_articles, "🔷 AI ニュース")
    content += process_articles(crypto_articles, "🔶 仮想通貨ニュース")

    with open(os.path.join(SAVE_DIR, filename), "w", encoding="utf-8") as f:
        f.write("\n".join(content))

    print(f"✅ 保存完了: {filename}")

# --------------------------------------------------
if __name__ == "__main__":
    main()

