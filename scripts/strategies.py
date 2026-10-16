"""Estrategias de análisis técnico, backtesting y estado actual de cada activo.

Estrategias (velas diarias):
- Ichimoku (9, 26, 52)
    Compra: el cierre queda sobre la nube, Tenkan sobre Kijun y el cierre supera
            al de hace 26 sesiones (Chikou libre). Se compra cuando las tres se
            cumplen juntas por primera vez.
    Venta:  el cierre cae bajo la nube o Tenkan cruza bajo Kijun.
- Medias móviles EMA 9, EMA 18 y SMA 30
    Compra: la EMA 9 y la EMA 18 quedan ambas sobre la SMA 30.
    Venta:  la EMA 9 y la EMA 18 quedan ambas bajo la SMA 30.

Backtest: solo compras (comprado o fuera), todo el capital en cada operación.
La señal se calcula con el cierre de un día y se ejecuta en la apertura del día
siguiente. Costo de 0,05% por cada compra o venta.

Genera:
- data/signals.json        estado de cada estrategia por activo y resumen del backtest
- data/strat/<TICKER>.json series para graficar (líneas, nube, operaciones, capital)

Estas señales ya no generan alertas: el buzón y los correos son solo de la estrategia momentum
que replica la simulación (scripts/momentum.py).
"""
import json
import os
from datetime import date, timedelta

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
COST = 0.0005
RECENT = 3  # sesiones en que una señal se considera "nueva"
WINDOWS = (6, 12, 18, 24)  # meses de backtest

TICKERS = ["QQQ", "NVDA", "AMD", "INTC", "MU", "SNDK", "WDC", "STX", "NTAP", "DELL",
           "FLEX", "AEHR", "AXTI", "DDOG", "ASTS", "LUNR", "SPCX", "HYMC", "MP",
           "ACWI", "SP500", "NASDAQ"]


def ema(v, n):
    k, out, e = 2 / (n + 1), [], None
    for i, x in enumerate(v):
        e = x if e is None else x * k + e * (1 - k)
        out.append(e if i >= n - 1 else None)
    return out


def sma(v, n):
    out, s = [], 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def midpoint(h, l, n):
    return [(max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2 if i >= n - 1 else None
            for i in range(len(h))]


def shift(v, k):
    """Desplaza la serie k posiciones hacia adelante (el valor de i aparece en i+k)."""
    return [None] * k + v[:len(v) - k] if k > 0 else v


# ---------- Señales: devuelven, por cada vela, 1 = condición de compra, -1 = venta, 0 = nada ----------

def ichimoku(bars):
    h = [b[2] for b in bars]
    l = [b[3] for b in bars]
    c = [b[4] for b in bars]
    tenkan, kijun, b52 = midpoint(h, l, 9), midpoint(h, l, 26), midpoint(h, l, 52)
    span_a_raw = [(t + k) / 2 if t is not None and k is not None else None for t, k in zip(tenkan, kijun)]
    span_a, span_b = shift(span_a_raw, 26), shift(b52, 26)  # la nube que corresponde a cada día
    sig, why = [], []
    for i in range(len(c)):
        if None in (tenkan[i], kijun[i], span_a[i], span_b[i]) or i < 26:
            sig.append(0); why.append("")
            continue
        top, bot = max(span_a[i], span_b[i]), min(span_a[i], span_b[i])
        bull = c[i] > top and tenkan[i] > kijun[i] and c[i] > c[i - 26]
        bear = c[i] < bot or tenkan[i] < kijun[i]
        sig.append(1 if bull else -1 if bear else 0)
        pos = "sobre la nube" if c[i] > top else "bajo la nube" if c[i] < bot else "dentro de la nube"
        tk = "Tenkan sobre Kijun" if tenkan[i] > kijun[i] else "Tenkan bajo Kijun"
        ch = "Chikou sobre el precio de hace 26 sesiones" if c[i] > c[i - 26] else "Chikou bajo el precio de hace 26 sesiones"
        why.append(f"Precio {pos}, {tk}, {ch}")
    # Nube futura: los 26 valores que todavía no llegan
    fut_a, fut_b = span_a_raw[-26:], b52[-26:]
    lines = {"tenkan": tenkan, "kijun": kijun, "spanA": span_a, "spanB": span_b}
    return sig, why, lines, (fut_a, fut_b)


def medias(bars):
    c = [b[4] for b in bars]
    e9, e18, s30 = ema(c, 9), ema(c, 18), sma(c, 30)
    sig, why = [], []
    for i in range(len(c)):
        if None in (e9[i], e18[i], s30[i]):
            sig.append(0); why.append("")
            continue
        up = e9[i] > s30[i] and e18[i] > s30[i]
        dn = e9[i] < s30[i] and e18[i] < s30[i]
        sig.append(1 if up else -1 if dn else 0)
        gap = (min(e9[i], e18[i]) / s30[i] - 1) * 100 if up else (max(e9[i], e18[i]) / s30[i] - 1) * 100
        if up:
            why.append(f"EMA 9 y EMA 18 sobre la SMA 30 (la más baja a {gap:+.2f}%)")
        elif dn:
            why.append(f"EMA 9 y EMA 18 bajo la SMA 30 (la más alta a {gap:+.2f}%)")
        else:
            arriba = "EMA 9" if e9[i] > s30[i] else "EMA 18"
            why.append(f"Cruce a medias: solo la {arriba} está sobre la SMA 30")
    return sig, why, {"ema9": e9, "ema18": e18, "sma30": s30}


# ---------- Backtest ----------

def backtest(bars, sig):
    """Comprado/fuera. Señal al cierre del día i, ejecución en la apertura del día i+1."""
    pos, entry, entry_d = 0, None, None
    cash, shares = 1.0, 0.0
    trades, equity, events = [], [], []
    prev = 0
    for i, b in enumerate(bars):
        d, o, c = b[0], b[1], b[4]
        if i > 0:
            want = prev  # señal del día anterior
            if want == 1 and pos == 0:
                shares, cash = cash * (1 - COST) / o, 0.0
                pos, entry, entry_d = 1, o, d
                events.append({"d": d, "t": "buy", "p": o})
            elif want == -1 and pos == 1:
                cash, shares = shares * o * (1 - COST), 0.0
                trades.append({"in": entry_d, "pin": entry, "out": d, "pout": o, "ret": o / entry * (1 - COST) ** 2 - 1})
                events.append({"d": d, "t": "sell", "p": o})
                pos = 0
        equity.append(cash + shares * c)
        # Una nueva condición solo cuenta si cambia respecto al estado de posición
        prev = sig[i]
    open_trade = None
    if pos == 1:
        last = bars[-1][4]
        open_trade = {"in": entry_d, "pin": entry, "ret": last / entry * (1 - COST) - 1}
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    wins = [t["ret"] for t in trades if t["ret"] > 0]
    losses = [t["ret"] for t in trades if t["ret"] <= 0]
    in_mkt = sum(1 for i in range(1, len(bars)) if any(t["in"] <= bars[i][0] < t["out"] for t in trades)
                 or (open_trade and bars[i][0] >= open_trade["in"]))
    return {
        "trades": len(trades),
        "winRate": len(wins) / len(trades) if trades else None,
        "totalRet": equity[-1] - 1,
        "buyHold": bars[-1][4] / bars[0][1] - 1,
        "maxDD": mdd,
        "avgTrade": sum(t["ret"] for t in trades) / len(trades) if trades else None,
        "profitFactor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "exposure": in_mkt / max(1, len(bars) - 1),
        "open": open_trade,
        "list": trades[-30:],
    }, equity, events


def months_ago(d, n):
    y, m, day = map(int, d[:10].split("-"))
    m -= n
    while m <= 0:
        m, y = m + 12, y - 1
    return f"{y:04d}-{m:02d}-{min(day, 28):02d}" if day > 28 else f"{y:04d}-{m:02d}-{day:02d}"


def windows(bars, sig):
    """Backtest de los últimos N meses. Los indicadores usan toda la historia;
    la cuenta parte sin posición en el primer día de la ventana."""
    out = {}
    for n in WINDOWS:
        start = months_ago(bars[-1][0], n)
        i = next((k for k, b in enumerate(bars) if b[0] >= start), 0)
        if i == 0 and date.fromisoformat(bars[0][0][:10]) > date.fromisoformat(start) + timedelta(days=10):
            continue  # no hay historia suficiente para esa ventana
        st, _, _ = backtest(bars[i:], sig[i:])
        st.pop("list")
        st["from"] = bars[i][0]
        out[f"{n}m"] = st
    return out


def state(bars, sig, why, bt, events):
    """Estado actual para las alertas."""
    n = len(bars)
    last_ev = events[-1] if events else None
    pending = None
    in_pos = bt["open"] is not None
    if sig[-1] == 1 and not in_pos:
        pending = "buy"
    elif sig[-1] == -1 and in_pos:
        pending = "sell"
    recent_ev = last_ev and last_ev["d"] >= bars[max(0, n - RECENT)][0]
    if pending == "buy":
        code, label = "buy_new", "Señal de COMPRA: se ejecuta en la próxima apertura"
    elif pending == "sell":
        code, label = "sell_new", "Señal de VENTA: se ejecuta en la próxima apertura"
    elif in_pos and recent_ev and last_ev["t"] == "buy":
        code, label = "buy_recent", f"Compra reciente ({last_ev['d']})"
    elif not in_pos and recent_ev and last_ev["t"] == "sell":
        code, label = "sell_recent", f"Venta reciente ({last_ev['d']})"
    elif in_pos:
        code, label = "long", f"Comprado desde {bt['open']['in']}"
    else:
        code, label = "flat", "Fuera del mercado, esperando compra"
    return {"code": code, "label": label, "detail": why[-1], "date": bars[-1][0], "lastEvent": last_ev}


def future_dates(last, k):
    d, out = date.fromisoformat(last), []
    while len(out) < k:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d.isoformat())
    return out


def r4(v):
    return None if v is None else round(v, 4)


def main():
    os.makedirs(os.path.join(DATA, "strat"), exist_ok=True)
    out = {"rules": {
        "ichimoku": "Compra cuando el cierre está sobre la nube, Tenkan sobre Kijun y el cierre supera al de hace 26 sesiones. Venta cuando el cierre cae bajo la nube o Tenkan cruza bajo Kijun.",
        "medias": "Compra cuando la EMA 9 y la EMA 18 quedan ambas sobre la SMA 30. Venta cuando ambas quedan bajo la SMA 30.",
        "backtest": "Velas diarias, solo compras, todo el capital por operación. Señal al cierre, ejecución en la apertura siguiente. Costo 0,05% por lado. Cada período parte sin posición en su primer día; los indicadores usan toda la historia.",
    }, "tickers": {}}
    for t in TICKERS:
        try:
            with open(os.path.join(DATA, f"{t}.json")) as f:
                bars = json.load(f)["daily"]
        except (OSError, ValueError, KeyError):
            continue
        if len(bars) < 120:
            continue
        si, wi, li, (fa, fb) = ichimoku(bars)
        sm, wm, lm = medias(bars)
        bti, eqi, evi = backtest(bars, si)
        btm, eqm, evm = backtest(bars, sm)
        out["tickers"][t] = {
            "ichimoku": {"state": state(bars, si, wi, bti, evi), "bt": {k: v for k, v in bti.items() if k != "list"}, "bts": windows(bars, si)},
            "medias": {"state": state(bars, sm, wm, btm, evm), "bt": {k: v for k, v in btm.items() if k != "list"}, "bts": windows(bars, sm)},
            "from": bars[0][0], "to": bars[-1][0],
        }
        dates = [b[0] for b in bars]
        fut = future_dates(dates[-1], 26)
        strat = {
            "dates": dates,
            "ichimoku": {**{k: [r4(x) for x in v] for k, v in li.items()},
                         "future": {"dates": fut, "spanA": [r4(x) for x in fa], "spanB": [r4(x) for x in fb]},
                         "events": evi, "equity": [r4(x) for x in eqi], "trades": bti["list"]},
            "medias": {**{k: [r4(x) for x in v] for k, v in lm.items()},
                       "events": evm, "equity": [r4(x) for x in eqm], "trades": btm["list"]},
        }
        with open(os.path.join(DATA, "strat", f"{t}.json"), "w") as f:
            json.dump(strat, f, separators=(",", ":"))
    with open(os.path.join(DATA, "signals.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Estrategias calculadas para {len(out['tickers'])} activos")


if __name__ == "__main__":
    main()
