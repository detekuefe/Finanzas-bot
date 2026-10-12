"""Descarga precios de Yahoo Finance (yfinance) y los guarda en data/.

- data/<TICKER>.json        velas diarias (2 años, se acumulan) y semanales (10 años)
- data/intra/<TICKER>.json  velas de 5 minutos por sesión, con premarket (se acumulan)
- data/summary.json         último precio, cierre previo y cierres recientes de cada activo

Lo ejecuta la acción "Actualizar datos" de GitHub cada 15 minutos en horario de mercado.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

TICKERS = ["QQQ", "NVDA", "AMD", "INTC", "MU", "SNDK", "WDC", "STX", "NTAP", "DELL",
           "FLEX", "AEHR", "AXTI", "DDOG", "ASTS", "LUNR", "SPCX", "HYMC", "MP"]
MACRO = {"US10Y": "^TNX", "BRENT": "BZ=F", "VIX": "^VIX"}
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
KEEP_INTRA_DAYS = 250


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    os.replace(tmp, path)


def frame_for(df, symbol):
    """Devuelve las columnas OHLCV de un símbolo desde una descarga múltiple."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        lv0 = df.columns.get_level_values(0)
        if symbol in lv0:
            sub = df[symbol]
        elif symbol in df.columns.get_level_values(1):
            sub = df.xs(symbol, axis=1, level=1)
        else:
            return None
    else:
        sub = df
    sub = sub.dropna(subset=["Close"])
    return sub if not sub.empty else None


def bars(sub, intraday=False):
    out = []
    for ts, r in sub.iterrows():
        key = int(ts.timestamp()) if intraday else ts.strftime("%Y-%m-%d")
        vol = r.get("Volume")
        out.append([key, round(float(r["Open"]), 4), round(float(r["High"]), 4),
                    round(float(r["Low"]), 4), round(float(r["Close"]), 4),
                    int(vol) if pd.notna(vol) else None])
    return out


def merge(old, new):
    m = {r[0]: r for r in old or []}
    for r in new:
        m[r[0]] = r
    return [m[k] for k in sorted(m)]


def download(symbols, **kw):
    try:
        return yf.download(symbols, group_by="ticker", auto_adjust=False, progress=False,
                           threads=True, **kw)
    except Exception as e:  # noqa: BLE001 - se informa y se sigue con lo que haya
        print(f"Descarga fallida {kw}: {e}", file=sys.stderr)
        return None


def main():
    symbols = TICKERS + list(MACRO.values())
    first_run = not os.path.exists(os.path.join(DATA, "summary.json"))
    daily_all = download(symbols, period="2y", interval="1d")
    weekly_all = download(symbols, period="10y", interval="1wk")
    intra_all = download(TICKERS, period="60d" if first_run else "5d", interval="5m", prepost=True)

    summary = load(os.path.join(DATA, "summary.json"), {"tickers": {}, "macro": {}})
    ok = 0
    for t in TICKERS:
        path = os.path.join(DATA, f"{t}.json")
        doc = load(path, {"daily": [], "weekly": []})
        d, w = frame_for(daily_all, t), frame_for(weekly_all, t)
        if d is not None:
            doc["daily"] = merge(doc["daily"], bars(d))
            ok += 1
        if w is not None:
            doc["weekly"] = bars(w)
        save(path, doc)

        ipath = os.path.join(DATA, "intra", f"{t}.json")
        idoc = load(ipath, {"days": {}})
        i = frame_for(intra_all, t)
        if i is not None:
            local = i.index.tz_convert("America/New_York")
            for day, part in i.groupby(local.date):
                k = day.isoformat()
                idoc["days"][k] = merge(idoc["days"].get(k), bars(part, intraday=True))
            for k in sorted(idoc["days"])[:-KEEP_INTRA_DAYS]:
                del idoc["days"][k]
            save(ipath, idoc)

        if doc["daily"]:
            last_intra = None
            if idoc["days"]:
                last_day = max(idoc["days"])
                last_intra = idoc["days"][last_day][-1]
            closes = [[r[0], r[4]] for r in doc["daily"][-260:]]
            summary["tickers"][t] = {"closes": closes, "lastBar": last_intra}

    for name, sym in MACRO.items():
        d = frame_for(daily_all, sym)
        if d is not None:
            summary["macro"][name] = [[r[0], r[4]] for r in bars(d)[-260:]]

    summary["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(os.path.join(DATA, "summary.json"), summary)
    print(f"Actualizados {ok} de {len(TICKERS)} activos")
    if ok == 0:
        sys.exit("Yahoo Finance no devolvió datos")


if __name__ == "__main__":
    main()
