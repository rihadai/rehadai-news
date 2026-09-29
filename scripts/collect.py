"""リハダイ NEWS 記事収集スクリプト

GitHub Actions から 1日3回（5時・12時・17時 JST）実行される。
1. 利用規約で利用が認められている配信元だけから新着を取得
2. Claude API で「リハ職に関係あるか」を判定し、自分の言葉で要約・分類
3. data/articles.json に追記（重複除外・最大 MAX_KEEP 件）

【権利面のルール】
- 取得するのはタイトル・リンク・本文テキスト（要約の材料）のみ。画像は一切取得しない。
- 厚生労働省：政府標準利用規約準拠で商用利用可。出典と「加工して作成」の旨を必ず表示。
- PubMed：論文の書誌情報をもとに自分の言葉で要約し、抄録の文章は転載しない。PubMedへリンク。
- 職能団体・学会サイトは営利利用不可やリンク制限があるため、許可が取れるまで対象外。
"""
import json, os, re, sys, time, html, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "articles.json")

MODEL = "claude-sonnet-5-5"
MAX_KEEP = 300            # サイトに残す記事数
MAX_NEW_PER_SOURCE = 5    # 1回の実行で各配信元から追加する上限
# 「学会・研修」は開催日・締切などの構造化データが必要なため、研修情報の配信元が決まるまで自動分類の対象外
CATS = ["制度・診療報酬", "研究・エビデンス", "PT", "OT", "ST", "働き方"]

MHLW_RSS = "https://www.mhlw.go.jp/stf/news.rdf"
NOTE_RSS = "https://note.com/rehadai/rss"   # 自分のnote（サイトの「noteの最新記事」用）
NOTE_DATA = os.path.join(ROOT, "data", "note.json")
PUBMED_TERM = (
    '("stroke rehabilitation"[tiab] OR "physical therapy"[tiab] OR physiotherapy[tiab] '
    'OR "occupational therapy"[tiab] OR "speech therapy"[tiab] OR "speech-language"[tiab] '
    'OR "dysphagia rehabilitation"[tiab] OR "musculoskeletal rehabilitation"[tiab]) '
    'AND (randomized controlled trial[pt] OR systematic review[pt] OR meta-analysis[pt])'
)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
UA = {"User-Agent": "rehadai-news-bot/1.0 (+contact via site)"}


# ---------- 共通 ----------
def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        return r.read(), ctype

def html_to_text(raw, limit=6000):
    t = raw.decode("utf-8", "ignore")
    t = re.sub(r"(?is)<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", t)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", html.unescape(t)).strip()
    return t[:limit]

def claude(system, user, max_tokens=1500, tries=3):
    """通信エラーやJSONの崩れは少し待って再試行する"""
    for i in range(tries):
        try:
            return _claude_once(system, user, max_tokens)
        except Exception as e:
            if i == tries - 1:
                raise
            print("claude retry:", e, file=sys.stderr)
            time.sleep(5 * (i + 1))

def _claude_once(system, user, max_tokens):
    key = os.environ["ANTHROPIC_API_KEY"]
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    text = "".join(b.get("text", "") for b in data["content"] if b["type"] == "text")
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


# ---------- 収集 ----------
def fetch_mhlw():
    raw, _ = http_get(MHLW_RSS)
    ns = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
    root = ET.fromstring(raw)
    items = []
    for it in root.findall("rss:item", ns):
        items.append({
            "title": (it.findtext("rss:title", "", ns) or "").strip(),
            "url": (it.findtext("rss:link", "", ns) or "").strip(),
            "date": (it.findtext("dc:date", "", ns) or "")[:10],
        })
    return items

def fetch_pubmed():
    q = urllib.parse.urlencode({"db": "pubmed", "term": PUBMED_TERM, "reldate": 3,
                                "datetype": "edat", "retmax": 30, "retmode": "json", "sort": "pub_date"})
    ids = json.loads(http_get(EUTILS + "esearch.fcgi?" + q)[0])["esearchresult"]["idlist"]
    if not ids:
        return []
    time.sleep(0.5)
    raw, _ = http_get(EUTILS + "efetch.fcgi?" + urllib.parse.urlencode(
        {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))
    out = []
    for art in ET.fromstring(raw).iter("PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = "".join(art.find(".//ArticleTitle").itertext()) if art.find(".//ArticleTitle") is not None else ""
        abstract = " ".join("".join(a.itertext()) for a in art.findall(".//AbstractText"))
        out.append({
            "title": title.strip(), "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "journal": art.findtext(".//Journal/Title", ""),
            "types": [t.text for t in art.findall(".//PublicationType")],
            "abstract": abstract[:5000],
        })
    return out


# ---------- AI 判定・要約 ----------
SYSTEM = f"""あなたはリハビリ専門職（PT・OT・ST）向けニュースサイトの編集者です。
出力は JSON のみ。前置きやコードブロックは付けないこと。

守ること：
- 元の文章を書き写さない。事実（日付・数値・対象・結果）を拾い、自分の言葉で書き直す。
- 臨床での判断を断定・推奨しない（「〜すべき」「〜が有効なので行う」は禁止）。研究や通知で示された事実として書く。
- 誇張しない。わからないことは書かない。
- カテゴリは次から1つ：{", ".join(CATS)}"""

def pick_mhlw(items):
    """タイトルだけでリハ職に関係ある新着を選ぶ（安価な一次判定）"""
    if not items:
        return []
    listing = "\n".join(f"{i}: {x['title']}" for i, x in enumerate(items))
    res = claude(SYSTEM, f"""厚生労働省の新着情報です。理学療法士・作業療法士・言語聴覚士の仕事に関係するもの
（診療報酬・介護報酬・医療/介護制度・リハビリ・障害福祉・高齢者・医療職の働き方・国家試験など）の番号を、
関係が強い順に最大{MAX_NEW_PER_SOURCE}件選んでください。無ければ空配列。
{listing}
出力形式：{{"ids":[番号,...]}}""", 300)
    return [items[i] for i in res.get("ids", []) if 0 <= i < len(items)]

def summarize(kind, title, text, extra=""):
    return claude(SYSTEM, f"""次の{kind}を、リハ職向けに紹介する記事データにしてください。
タイトル：{title}
{extra}
本文（要約の材料。書き写し禁止）：
{text}

出力形式：
{{"relevant": true/false（リハ職に関係なければ false）,
 "title": "日本語の見出し（40字以内、事実ベース）",
 "cat": "カテゴリ",
 "body": "要約（日本語120〜180字、自分の言葉で）",
 "points": ["押さえておきたい事実（30字前後）", "…"]（2〜3個）}}""")


def update_note_list():
    """自分のnoteのRSSから最新記事を data/note.json に保存"""
    try:
        from email.utils import parsedate_to_datetime
        root = ET.fromstring(http_get(NOTE_RSS)[0])
        out = []
        for it in root.iter("item"):
            d = it.findtext("pubDate", "")
            try:
                d = parsedate_to_datetime(d).astimezone(JST).strftime("%Y-%m-%d")
            except Exception:
                d = ""
            out.append({"title": it.findtext("title", "").strip(), "url": it.findtext("link", "").strip(), "date": d})
        with open(NOTE_DATA, "w", encoding="utf-8") as f:
            json.dump(out[:5], f, ensure_ascii=False, indent=1)
    except Exception as e:
        print("note rss failed:", e, file=sys.stderr)


# ---------- メイン ----------
def main():
    update_note_list()
    try:
        with open(DATA, encoding="utf-8") as f:
            articles = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        articles = []
    seen = {a["url"] for a in articles}
    next_id = max([a["id"] for a in articles], default=0) + 1
    today = datetime.now(JST).strftime("%Y-%m-%d")
    added = []

    def add(src, url, date, s, credit):
        nonlocal next_id
        if not s.get("relevant") or s.get("cat") not in CATS:
            return
        if not s.get("title") or not s.get("body"):   # 中身が欠けた出力は載せない
            return
        s["title"] = s["title"][:60]
        s["body"] = s["body"][:300]
        added.append({"id": next_id, "cat": s["cat"], "src": src, "date": date or today, "views": 0,
                      "title": s["title"], "body": s["body"], "points": s.get("points", [])[:3],
                      "url": url, "credit": credit})
        next_id += 1

    # 厚生労働省
    try:
        new = [x for x in fetch_mhlw() if x["url"] and x["url"] not in seen]
        for x in pick_mhlw(new[:60]):
            try:
                raw, ctype = http_get(x["url"])
                if "html" not in ctype:      # PDF等は本文を読めないので見送る
                    continue
                s = summarize("厚生労働省の発表", x["title"], html_to_text(raw))
                add("厚生労働省", x["url"], x["date"], s,
                    f"出典：厚生労働省ホームページ（{x['url']}）を加工して作成")
                time.sleep(1)
            except Exception as e:
                print("mhlw item skip:", x["url"], e, file=sys.stderr)
    except Exception as e:
        print("mhlw fetch failed:", e, file=sys.stderr)

    # PubMed
    try:
        papers = [p for p in fetch_pubmed() if p["url"] not in seen and p["abstract"]]
        count = 0
        for p in papers:
            if count >= MAX_NEW_PER_SOURCE:
                break
            s = summarize("論文", p["title"], p["abstract"],
                          f"掲載誌：{p['journal']}／論文種別：{', '.join(p['types'])}")
            before = len(added)
            add("PubMed", p["url"], today, s,
                f"出典：PubMed（{p['url']}）掲載の論文情報をもとに作成")
            count += len(added) - before
            time.sleep(1)
    except Exception as e:
        print("pubmed failed:", e, file=sys.stderr)

    if not added:
        print("新着なし")
        return
    articles = sorted(added + articles, key=lambda a: (a["date"], a["id"]), reverse=True)[:MAX_KEEP]
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=1)
    print(f"{len(added)}件追加")

if __name__ == "__main__":
    main()
