#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
▶ AI／仮想通貨ニュースを自動要約し、Obsidian Vault に保存
   └ 取得対象 : 「前日 0:00 JST 〜 当日 23:59 JST」 に公開された記事のみ
   └ ChatGPT で衝撃度・面白さ順に TOP5 を抽出
   └ 個人情報やキー類は .env で管理（.gitignore に追加必須）
"""

import os, re, time, email.utils as eut
from datetime import datetime, timedelta, timezone
import pytz
import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import openai

# --------------------------------------------------
# 0) 日本時間ヘルパ
# --------------------------------------------------
JST = pytz.timezone("Asia/Tokyo")
def jst_now() -> datetime:
    return datetime.now(JST)

# --------------------------------------------------
# 1) .env 読み込み
# --------------------------------------------------
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SAVE_DIR       = os.getenv("SAVE_DIR")
NICKNAME       = os.getenv("NICKNAME")
PROFILE        = os.getenv("PROFILE")
AI_FEEDS       = [u.strip() for u in os.getenv("AI_FEEDS", "").split(",") if u.strip()]
CRYPTO_FEEDS   = [u.strip() for u in os.getenv("CRYPTO_FEEDS", "").split(",") if u.strip()]

if not all([OPENAI_API_KEY, SAVE_DIR, NICKNAME, PROFILE]):
    raise ValueError("OPENAI_API_KEY / SAVE_DIR / NICKNAME / PROFILE が .env にありません")

# --------------------------------------------------
# 2) OpenAI クライアント
# --------------------------------------------------
client = openai.OpenAI(api_key=OPENAI_API_KEY)  # openai>=1.x

# --------------------------------------------------
# 3) 保存フォルダ
# --------------------------------------------------
os.makedirs(SAVE_DIR, exist_ok=True)

# --------------------------------------------------
# 4) キーワード
# --------------------------------------------------
KEYWORDS_AI     = ["ai", "人工知能", "生成ai", "chatgpt", "gpt", "openai"]
KEYWORDS_CRYPTO = ["仮想通貨", "暗号資産", "ビットコイン", "ブロックチェーン", "crypto"]

# --------------------------------------------------
# 5) 日付判定
# --------------------------------------------------
def is_within_today(entry, now_jst: datetime) -> bool:
    """前日0:00〜当日23:59(JST) に公開されたか判定"""
    pub_dt = None

    # (a) published_parsed (struct_time) がある場合
    if getattr(entry, "published_parsed", None):
        pub_dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=JST)
    # (b) published 文字列 → RFC822 解析
    elif getattr(entry, "published", None):
        try:
            tup = eut.parsedate(entry.published)
            pub_dt = datetime.fromtimestamp(time.mktime(tup), tz=JST)
        except Exception:
            return False
    else:
        return False  # 日付不明は除外

    start = (now_jst - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    end   =  now_jst.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start <= pub_dt <= end

# --------------------------------------------------
# 6) RSS → 候補取得 → ChatGPT ランキング
# --------------------------------------------------
def fetch_top5(feed_urls, keywords, now_jst) -> list:
    candidates = []
    for url in feed_urls:
        parsed = feedparser.parse(url)
        for e in parsed.entries:
            # 対象期間+キーワード判定
            ttl = e.title
            summary = getattr(e, "summary", "")
            if not is_within_today(e, now_jst):
                continue
            if not any(k in (ttl+summary).lower() for k in keywords):
                continue
            candidates.append(
                {"title": ttl,
                 "url":   e.link,
                 "summary": summary[:120],
                 "published": getattr(e, "published", "不明")}
            )

    if not candidates:
        return []

    # ChatGPT に衝撃度ランキングを依頼
    lst = "\n".join(f"{i+1}. {c['title']} - {c['summary']}"
                    for i, c in enumerate(candidates))
    prompt = (
        "次のニュースの中から、衝撃度・面白さが高いものを5件だけ選び、"
        "番号だけカンマ区切りで返してください。\n" + lst
    )
    try:
        ans = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=20,
            temperature=0.3,
        ).choices[0].message.content
        idxs = [int(x) for x in re.findall(r"\d+", ans)][:5]
        top5 = [candidates[i-1] for i in idxs if 1 <= i <= len(candidates)]
        return top5
    except Exception:
        # 失敗したら先頭5件
        return candidates[:5]

# --------------------------------------------------
# 7) 本文スクレイピング & 要約・提案
# --------------------------------------------------
def fetch_text(url, limit=2000):
    try:
        html = requests.get(url, timeout=10).text
        soup = BeautifulSoup(html, "html.parser")
        text = "\n".join(p.get_text(" ", strip=True) for p in soup.find_all("p"))
        return text[:limit]
    except Exception as e:
        return f"(本文取得失敗: {e})"

def gpt_summary(fulltext):
    prompt = f"以下の記事を日本語で200字以内に要約してください。\n{fulltext}"
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=350,
        temperature=0.5,
    ).choices[0].message.content.strip()

def gpt_suggestion(summary):
    prompt = (
        f"以下のニュース要約を読んで、{PROFILE} が取るべき行動を"
        "3つ、箇条書きで提案してください（発信・副業・収益化など）。\n\n{summary}"
    )
    return client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.8,
    ).choices[0].message.content.strip()

def tag_from_suggestion(s):
    s = s.lower()
    tags = {"#副業", "#収益化案"}
    if "ai" in s or "人工知能" in s: tags.add("#AI")
    if any(k in s for k in ["仮想通貨", "ビットコイン", "暗号資産"]): tags.add("#仮想通貨")
    if "note" in s: tags.add("#note案")
    if "twitter" in s or "ポスト" in s or "xで" in s: tags.add("#X案")
    if "youtube" in s: tags.add("#YouTube案")
    if "kindle" in s: tags.add("#Kindle案")
    if "udemy" in s: tags.add("#Udemy案")
    if any(k in s for k in ["stand.fm", "音声配信"]): tags.add("#音声配信案")
    return " ".join(sorted(tags))

# --------------------------------------------------
# 8) Markdown 組み立て
# --------------------------------------------------
def build_section(articles, header):
    section = [f"## {header}\n"]
    for i, art in enumerate(articles, 1):
        body  = fetch_text(art["url"])
        summ  = gpt_summary(body)
        sugg  = gpt_suggestion(summ)
        tags  = tag_from_suggestion(sugg)

        section += [
            f"### 〔{i}〕 {art['title']}",
            f"- **公開日:** {art['published']}",
            f"- **URL:** {art['url']}\n",
            f"**要約:** {summ}\n",
            f"**{NICKNAME}への提案:**\n{sugg}\n",
            tags + "\n"
        ]
    return section

# --------------------------------------------------
# 9) メイン
# --------------------------------------------------
def main():
    now = jst_now()
    ai_articles     = fetch_top5(AI_FEEDS,     KEYWORDS_AI,     now)
    crypto_articles = fetch_top5(CRYPTO_FEEDS, KEYWORDS_CRYPTO, now)

    today    = now.strftime("%Y-%m-%d")
    filename = f"news_{now.strftime('%Y%m%d')}.md"

    md = [f"# {today} の AI・仮想通貨ニュースまとめ\n"]
    md += build_section(ai_articles,     "🔷 AI ニュース")
    md += build_section(crypto_articles, "🔶 仮想通貨ニュース")

    with open(os.path.join(SAVE_DIR, filename), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"✅ 保存完了: {filename}")

# --------------------------------------------------
if __name__ == "__main__":
    main()

