"""毎週のnote下書き「今週のリハニュース」を作るスクリプト

noteには公式の投稿APIがなく、非公式の方法での自動投稿は規約上のリスクがあるため、
ここでは「下書きを自動で作る」までを担当する。
下書きは GitHub の Issue として届くので、自分のコメントを書き足してnoteに貼り付けて投稿する。
"""
import json, os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collect import claude, DATA, JST

SITE_URL = os.environ.get("SITE_URL", "")
VOL = os.environ.get("VOL", "1")

SYSTEM = """あなたは、臨床1年目のリハビリ専門職が書くnote「今週のリハニュース」の下書きを作る編集アシスタントです。
出力は JSON のみ。前置きやコードブロックは付けないこと。

守ること：
- 事実は、渡された記事データの範囲だけで書く。推測で数字や日付を足さない。
- 臨床での判断を断定・推奨しない。
- 書き手本人の感想や体験は絶対に書かない（そこは本人が書く欄として空けておく）。
- やわらかい「です・ます」調。専門用語は一言で補足する。"""

def main():
    with open(DATA, encoding="utf-8") as f:
        articles = json.load(f)
    since = (datetime.now(JST) - timedelta(days=7)).strftime("%Y-%m-%d")
    recent = [a for a in articles if a["date"] >= since]
    if len(recent) < 1:
        print("今週の記事がありません"); open("draft.md", "w").write(""); return

    listing = "\n\n".join(
        f"[{i}] {a['cat']}／{a['src']}／{a['date']}\n見出し：{a['title']}\n要約：{a['body']}\n要点：{' / '.join(a.get('points', []))}"
        for i, a in enumerate(recent[:40]))
    res = claude(SYSTEM, f"""今週サイトに載った記事です。リハ職（特に若手）にとって大事なものを3本選び、noteの下書きを作ってください。
分野がかたよらないようにし、制度の締切など期限のある話題は優先してください。

{listing}

出力形式：
{{"picks":[番号,番号,番号],
 "title_keywords":"3本の話題を「、」でつないだ短い言葉（全体30字以内）",
 "intro":"導入文（2〜3文。今週どんな話題があったか）",
 "items":[{{"heading":"見出し（25字以内）","text":"何があったか（150〜220字、事実のみ）"}}, ...]}}""", 2500)

    picks = [recent[i] for i in res["picks"] if 0 <= i < len(recent)]
    lines = [
        f"# 今週のリハニュース vol.{VOL}｜{res['title_keywords']}", "",
        res["intro"], "",
    ]
    for n, (item, a) in enumerate(zip(res["items"], picks), 1):
        lines += [
            f"## {n}. {item['heading']}", "",
            item["text"], "",
            f"出典：{a['src']}（{a['url']}）", "",
            "💬 1年目の自分が気になったこと", "",
            "（✍️ ここに自分の言葉でコメントを書く。1〜3文でOK）", "",
        ]
    lines += [
        "---", "",
        "毎日のリハニュースは「リハダイ NEWS」でまとめています。" + (f"\n{SITE_URL}" if SITE_URL else ""), "",
        "論文を探したいときは、アプリ「リハ論文ダイジェスト（リハダイ）」もどうぞ。", "",
        "#理学療法士 #作業療法士 #言語聴覚士 #リハビリ #医療ニュース",
    ]
    body = "\n".join(lines)
    guide = ("このIssueは毎週自動で作られるnoteの下書きです。\n"
             "1. ✍️ の3か所に自分のコメントを書く\n"
             "2. 事実に違和感がないか、出典リンクを開いてざっと確認する\n"
             "3. 下の本文をnoteに貼り付けて投稿する（1行目がタイトル）\n"
             "4. 投稿したらこのIssueを Close する\n\n---\n\n")
    with open("draft.md", "w", encoding="utf-8") as f:
        f.write(guide + body)
    with open("draft_title.txt", "w", encoding="utf-8") as f:
        f.write(f"note下書き vol.{VOL}｜{res['title_keywords']}")
    print("下書きを作成しました")

if __name__ == "__main__":
    main()
