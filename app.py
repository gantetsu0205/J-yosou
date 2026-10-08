import math
import re
import unicodedata
import urllib.parse
import urllib.request
import datetime as dt
from html.parser import HTMLParser
import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Jリーグ勝敗予想", page_icon="⚽", layout="wide")

LABEL = {1: "1 ホーム勝利", 0: "0 引き分け", 2: "2 アウェイ勝利"}
SEASON = 2026  # 2026/27シーズン
BASE_URL = "https://data.j-league.or.jp/SFMS01/search"  # Jリーグデータサイト 日程・結果
FRAME = {"J1": 1, "J2": 2, "J3": 3}  # competition_frame_ids
JST = dt.timezone(dt.timedelta(hours=9))

# ダミーデータ用のクラブ名（取得失敗時のみ使用）
DUMMY_TEAMS = {
    "J1": ["神戸", "柏", "広島", "町田", "FC東京", "横浜FM", "川崎F", "鹿島", "岡山", "浦和",
           "C大阪", "清水", "水戸", "京都", "長崎", "G大阪", "名古屋", "福岡", "東京V", "千葉"],
    "J2": ["大宮", "新潟", "今治", "札幌", "湘南", "秋田", "大分", "藤枝", "甲府", "宮崎",
           "八戸", "鳥栖", "富山", "横浜FC", "仙台", "いわき", "栃木C", "山形", "磐田", "徳島"],
    "J3": ["相模原", "熊本", "長野", "山口", "鳥取", "FC大阪", "高知", "松本", "鹿児島", "群馬",
           "福島", "讃岐", "滋賀", "岐阜", "愛媛", "奈良", "栃木SC", "金沢", "北九州", "琉球"],
}


# ---------- データ取得（Jリーグデータサイト） ----------
def norm(s):
    """全角英数を半角に統一（例: 第１節→第1節, Ｃ大阪→C大阪）"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


class _TableParser(HTMLParser):
    """標準ライブラリだけで <tr><td> の文字を集める（追加インストール不要）"""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_table(html, cat):
    """日程・結果テーブルを解析。列: シーズン,大会,節,試合日,K/O,ホーム,スコア,アウェイ,スタジアム,入場者,放送"""
    parser = _TableParser()
    parser.feed(html)
    rows = []
    for cells in parser.rows:
        if len(cells) < 8:
            continue
        t = [norm(c) for c in cells]
        m_round = re.search(r"第(\d+)節", t[2])
        m_date = re.search(r"(\d{2})/(\d{2})/(\d{2})", t[3])
        if not (m_round and m_date) or not t[1].startswith(cat):
            continue
        yy, mm, dd = map(int, m_date.groups())
        m_score = re.match(r"^(\d+)-(\d+)$", t[6])  # 未開催は "vs"
        hg, ag = (int(m_score.group(1)), int(m_score.group(2))) if m_score else (np.nan, np.nan)
        rows.append((cat, int(m_round.group(1)), dt.date(2000 + yy, mm, dd), t[4],
                     t[5], t[7], hg, ag, t[8] if len(t) > 8 else ""))
    return pd.DataFrame(rows, columns=["cat", "round", "date", "ko", "home", "away", "hg", "ag", "stadium"])


def fetch_category(cat):
    url = BASE_URL + "?" + urllib.parse.urlencode(
        {"competition_years": SEASON, "competition_frame_ids": FRAME[cat]})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (jleague-yosou-app)"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    df = parse_table(html, cat)
    if len(df) < 100:  # 38節×10試合=380試合が通常。極端に少なければ構造変更とみなす
        raise RuntimeError(f"試合数が想定より少ない: {len(df)}")
    return df


# ---------- ダミーデータ（フォールバック） ----------
def round_robin(teams):
    t, n, rounds = teams[:], len(teams), []
    for r in range(n - 1):
        pairs = []
        for i in range(n // 2):
            a, b = t[i], t[n - 1 - i]
            pairs.append((a, b) if (i + r) % 2 == 0 else (b, a))
        rounds.append(pairs)
        t = [t[0]] + [t[-1]] + t[1:-1]
    return rounds


def make_dummy(cat):
    rng = np.random.default_rng(42)
    today = dt.datetime.now(JST).date()
    teams = DUMMY_TEAMS[cat]
    power = {t: rng.normal(0, 0.3) for t in teams}
    first = round_robin(teams)
    rows = []
    for idx, pairs in enumerate(first + [[(b, a) for a, b in rd] for rd in first]):
        d = dt.date(2026, 8, 8) + dt.timedelta(days=7 * idx)
        for h, a in pairs:
            hg = ag = np.nan
            if d < today:
                hg = rng.poisson(1.4 * math.exp(power[h] - power[a] + 0.1))
                ag = rng.poisson(1.1 * math.exp(power[a] - power[h] - 0.1))
            rows.append((cat, idx + 1, d, "", h, a, hg, ag, ""))
    return pd.DataFrame(rows, columns=["cat", "round", "date", "ko", "home", "away", "hg", "ag", "stadium"])


@st.cache_data(ttl=1800, show_spinner="Jリーグデータサイトから取得中…")
def load_data():
    frames, real, errors = [], {}, {}
    for cat in ["J1", "J2", "J3"]:
        try:
            frames.append(fetch_category(cat))
            real[cat] = True
        except Exception as e:  # 取得・解析に失敗したカテゴリだけダミーに切替
            frames.append(make_dummy(cat))
            real[cat] = False
            errors[cat] = f"{type(e).__name__}: {e}"
    return pd.concat(frames, ignore_index=True), real, errors, dt.datetime.now(JST).strftime("%Y/%m/%d %H:%M")


# ---------- 予測モデル（Elo + ポアソン） ----------
def fit_model(played):
    played = played.sort_values("date")
    elo, K, HFA = {}, 20, 60
    for r in played.itertuples():
        rh, ra = elo.get(r.home, 1500), elo.get(r.away, 1500)
        e = 1 / (1 + 10 ** (-(rh - ra + HFA) / 400))
        s = 1 if r.hg > r.ag else (0.5 if r.hg == r.ag else 0)
        elo[r.home], elo[r.away] = rh + K * (s - e), ra - K * (s - e)

    gh = played.hg.mean() if len(played) else 1.4
    ga = played.ag.mean() if len(played) else 1.1
    k = 5  # 試合数が少ない時にリーグ平均へ寄せる強さ
    stats = {}
    for t in set(played.home) | set(played.away):
        h, a = played[played.home == t], played[played.away == t]
        stats[t] = dict(
            h_att=(h.hg.sum() + k * gh) / (len(h) + k) / gh,
            h_def=(h.ag.sum() + k * ga) / (len(h) + k) / ga,
            a_att=(a.ag.sum() + k * ga) / (len(a) + k) / ga,
            a_def=(a.hg.sum() + k * gh) / (len(a) + k) / gh,
        )
    return dict(elo=elo, gh=gh, ga=ga, stats=stats, HFA=HFA)


def predict(m, home, away):
    one = dict(h_att=1, h_def=1, a_att=1, a_def=1)
    sh, sa = m["stats"].get(home, one), m["stats"].get(away, one)
    lam_h = m["gh"] * sh["h_att"] * sa["a_def"]
    lam_a = m["ga"] * sa["a_att"] * sh["h_def"]
    pm_h = np.array([math.exp(-lam_h) * lam_h ** i / math.factorial(i) for i in range(11)])
    pm_a = np.array([math.exp(-lam_a) * lam_a ** i / math.factorial(i) for i in range(11)])
    mat = np.outer(pm_h, pm_a)
    mat /= mat.sum()
    pois = np.array([np.tril(mat, -1).sum(), np.trace(mat), np.triu(mat, 1).sum()])  # 勝/分/負

    diff = m["elo"].get(home, 1500) - m["elo"].get(away, 1500) + m["HFA"]
    e = 1 / (1 + 10 ** (-diff / 400))
    pd_ = max(0.15, 0.28 - abs(diff) / 2000)
    elo_p = np.clip(np.array([e - pd_ / 2, pd_, 1 - e - pd_ / 2]), 0.01, None)
    elo_p /= elo_p.sum()

    p = 0.5 * pois + 0.5 * elo_p
    p /= p.sum()
    return {1: p[0], 0: p[1], 2: p[2]}, lam_h, lam_a


# ---------- 画面 ----------
st.title("⚽ Jリーグ 勝敗予想")
df, real, errors, fetched_at = load_data()

c1, c2, c3 = st.columns([2, 2, 1])
cat = c1.selectbox("カテゴリー", ["J1", "J2", "J3"])
if c3.button("🔄 最新に更新"):
    st.cache_data.clear()
    st.rerun()

if real[cat]:
    st.caption(f"データ: Jリーグデータサイト（公式）／取得: {fetched_at}（30分キャッシュ）")
else:
    st.warning(f"{cat}は**ダミーデータ**で動作中です（公式サイトの取得に失敗）。成績・予測は実際のものではありません。")
    with st.expander("エラー詳細"):
        st.code(errors.get(cat, ""))

cdf = df[df.cat == cat]
rounds = sorted(cdf["round"].unique())
unfinished = cdf[cdf.hg.isna()]["round"]
default_idx = rounds.index(int(unfinished.min())) if len(unfinished) else len(rounds) - 1
rnd = c2.selectbox("節", rounds, index=default_idx, format_func=lambda x: f"第{x}節")

played = cdf[cdf.hg.notna()]
model = fit_model(played)
st.caption(f"学習に使った終了済み試合数: {len(played)}　／　表記: 1=ホーム勝ち, 0=引き分け, 2=アウェイ勝ち")

for r in cdf[cdf["round"] == rnd].sort_values(["date", "ko"]).itertuples():
    with st.container(border=True):
        st.caption(f"{r.date:%Y/%m/%d} {r.ko}　{r.stadium}")
        st.markdown(f"### {r.home}　vs　{r.away}")
        if not pd.isna(r.hg):
            res = 1 if r.hg > r.ag else (0 if r.hg == r.ag else 2)
            st.success(f"終了　{int(r.hg)} - {int(r.ag)}　（結果: {LABEL[res]}）")
        else:
            probs, lh, la = predict(model, r.home, r.away)
            st.caption(f"予想得点（期待値）: {lh:.2f} - {la:.2f}")
            for i, (k_, v) in enumerate(sorted(probs.items(), key=lambda x: -x[1])):
                a, b = st.columns([2, 3])
                a.markdown(f"**{i + 1}位　{LABEL[k_]}**" if i == 0 else f"{i + 1}位　{LABEL[k_]}")
                b.progress(float(v), text=f"{v * 100:.1f}%")
