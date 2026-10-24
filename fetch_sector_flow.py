"""
Compute cumulative intraday money flow (Chaikin approximation) per S&P 500 sector.
Output: sector_flow.json  (read by the Scriptable widget)

flow     = sum( MFM * typical_price * volume ) / 1e6,  MFM = ((C-L)-(H-C))/(H-L)
turnover = sum( typical_price * volume ) / 1e6   (so |flow| <= turnover always holds)
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0"}
WIKI_UA = {"User-Agent": "sector-flow/1.0 (personal project; github.com/toshikungary)"}
WORKERS = 6
MAX_FAIL_RATIO = 0.3  # abort (keep old JSON) if more than 30% of symbols fail

ZH = {
    "Information Technology": "科技",
    "Communication Services": "通訊服務",
    "Energy": "能源",
    "Health Care": "醫療保健",
    "Consumer Staples": "必需消費",
    "Utilities": "公用事業",
    "Industrials": "工業",
    "Materials": "原材料",
    "Real Estate": "房地產",
    "Financials": "金融",
    "Consumer Discretionary": "非必需消費",
}

# ---- 1. constituents -> sector map ----
html = requests.get(
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    headers=WIKI_UA, timeout=30,
).text
cons = pd.read_html(StringIO(html))[0]
cons["Symbol"] = cons["Symbol"].str.replace(".", "-", regex=False)  # BRK.B -> BRK-B
sector = dict(zip(cons["Symbol"], cons["GICS Sector"]))
sector = {s: g for s, g in sector.items() if g in ZH}


# ---- 2. fetch one symbol ----
def fetch(sym):
    for attempt in range(3):
        try:
            resp = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                params={"interval": "5m", "range": "1d", "includePrePost": "false"},
                headers=UA, timeout=15,
            )
            if resp.status_code == 429:
                time.sleep(2 * (attempt + 1))
                continue
            r = resp.json()["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            d = pd.DataFrame({
                "t": r["timestamp"], "h": q["high"], "l": q["low"],
                "c": q["close"], "v": q["volume"],
            }).dropna()
            if d.empty:
                return sym, None, None
            rng = (d.h - d.l).where(lambda x: x > 0)
            mfm = (((d.c - d.l) - (d.h - d.c)) / rng).fillna(0)
            tp = (d.h + d.l + d.c) / 3
            flow = (mfm * tp * d.v / 1e6).set_axis(d.t)
            turn = (tp * d.v / 1e6).set_axis(d.t)
            time.sleep(0.05)
            return sym, flow, turn
        except Exception:
            time.sleep(1)
    return sym, None, None


with ThreadPoolExecutor(WORKERS) as ex:
    res = list(ex.map(fetch, sector))

flows = {s: f for s, f, _ in res if f is not None}
turns = {s: t for s, _, t in res if t is not None}
failed = [s for s, f, _ in res if f is None]

total = len(sector)
print(f"ok {total - len(failed)}/{total}, failed {len(failed)}: {failed[:20]}")
if len(failed) > total * MAX_FAIL_RATIO:
    print("Too many failures; keeping previous sector_flow.json", file=sys.stderr)
    sys.exit(1)

# ---- 3. aggregate by sector, cumulative over time ----
F = pd.DataFrame(flows).fillna(0).sort_index()
T = pd.DataFrame(turns).fillna(0).sort_index()


def by_sec(D):
    return D.T.groupby(lambda s: ZH[sector[s]]).sum().T


cum = by_sec(F).cumsum()
turn = by_sec(T).cumsum()

# sanity check: |cum flow| must not exceed turnover
bad = [k for k in cum.columns if (cum[k].abs() > turn[k] + 1e-6).any()]
if bad:
    print(f"WARNING: flow > turnover for {bad}", file=sys.stderr)

out = {
    "total": total,
    "failed": failed,
    "times": [int(t) for t in cum.index],
    "series": {k: cum[k].round(0).tolist() for k in cum.columns},
    "turnover": {k: turn[k].round(0).tolist() for k in turn.columns},
}
with open("sector_flow.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False)
print("wrote sector_flow.json,", len(out["times"]), "bars")
