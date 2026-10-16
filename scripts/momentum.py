"""Estrategia de momentum sobre el Nasdaq-100 y las mayores del S&P 500.

Regla propuesta:
- El primer día hábil de cada mes, al cierre, ordena las acciones por momentum (promedio del retorno
  de 3, 6 y 12 meses) y compra en partes iguales las 10 mejores; vende las que salieron del grupo.
- Siempre invertida, sin filtro de mercado (Jaime lo eligió el 2026-10-16: entre 2018 y 2026 el filtro de
  SPY sobre su media de 200 días rindió la mitad sin bajar mucho la caída máxima).
Además prueba variantes (5/10/20 acciones, otras medidas de momentum, filtro diario, mensual o sin filtro)
para ver si la regla elegida es robusta. Compara contra comprar y mantener SPY, QQQ y todo el universo
en igual peso, a 1 y 2 años. Costo de 0,05% por compra o venta.

Escribe data/momentum.json, agrega las alertas nuevas a data/alerts_log.json y, al cierre, a alertas.md
(la acción las manda por correo como issue).
"""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
COST = 0.0005
LB = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
SCORES = {"mix": "promedio 3/6/12 meses", "12m": "12 meses", "6m": "6 meses", "12-1": "12 meses sin el último"}
REGIMES = {"d": "filtro diario SPY > media 200", "m": "filtro mensual SPY > media 200", "no": "sin filtro"}
DEFAULT = "n10_mix_no"


def load(name, default):
    try:
        with open(os.path.join(DATA, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def prepare(U):
    D = U["dates"]
    C = {}
    for t, xs in U["closes"].items():
        last, out = None, []
        for x in xs:  # rellena huecos sueltos con el cierre anterior; antes de cotizar queda None
            last = x if x is not None else last
            out.append(last)
        C[t] = out
    return D, C


def sma(xs, i, n):
    w = xs[i - n + 1:i + 1] if i >= n - 1 else []
    return sum(w) / n if w and None not in w else None


def score(C, t, i, kind):
    xs = C[t]
    def r(k, end=i):
        a, b = (xs[end - k] if end - k >= 0 else None), xs[end]
        return b / a - 1 if a and b else None
    if kind == "mix":
        rs = [r(LB["3m"]), r(LB["6m"]), r(LB["12m"])]
        return None if None in rs else sum(rs) / 3
    if kind == "12-1":
        a, b = (xs[i - LB["12m"]] if i - LB["12m"] >= 0 else None), xs[i - LB["1m"]]
        return b / a - 1 if a and b else None
    return r(LB[kind])


def ranking(C, stocks, i, kind):
    sc = [(score(C, t, i, kind), t) for t in stocks]
    return sorted([s for s in sc if s[0] is not None], reverse=True)


def simulate(D, C, stocks, s, n, kind, regime, regime_ok, first_day):
    """Simula desde el índice s hasta el final. Devuelve curva diaria, eventos y posiciones finales."""
    val, w, eq, events, cash_days = 1.0, {}, [1.0], [], 0
    def rebalance(i, why):
        nonlocal val, w
        target = [t for _, t in ranking(C, stocks, i, kind)[:n]]
        new = {t: 1 / n for t in target}
        turnover = sum(abs(new.get(t, 0) - w.get(t, 0)) for t in set(new) | set(w))
        val *= 1 - turnover * COST
        buys, sells = [t for t in target if t not in w], [t for t in w if t not in new]
        if buys or sells:
            events.append({"d": D[i], "why": why, "buy": buys, "sell": sells, "hold": target})
        w = new
    def to_cash(i, why):
        nonlocal val, w
        if w:
            val *= 1 - sum(w.values()) * COST
            events.append({"d": D[i], "why": why, "buy": [], "sell": sorted(w, key=lambda t: -w[t]), "hold": []})
        w = {}
    on = regime == "no" or regime_ok[s]
    if on:
        rebalance(s, "inicio")
    for i in range(s + 1, len(D)):
        g = {t: wt * C[t][i] / C[t][i - 1] for t, wt in w.items()}
        cash = 1 - sum(w.values())
        val *= cash + sum(g.values())
        tot = cash + sum(g.values())
        w = {t: v / tot for t, v in g.items()}
        if not w:
            cash_days += 1
        if regime == "d":
            if on and not regime_ok[i]:
                on = False
                to_cash(i, "mercado")
            elif not on and regime_ok[i]:
                on = True
                rebalance(i, "mercado")
            elif on and first_day[i]:
                rebalance(i, "mes")
        elif first_day[i]:
            if regime == "m" and not regime_ok[i]:
                to_cash(i, "mercado")
            else:
                rebalance(i, "mes")
        eq.append(round(val, 4))
    return eq, events, w, cash_days / max(1, len(D) - s - 1)


def stats(eq):
    peak, dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    return {"ret": round(eq[-1] / eq[0] - 1, 4), "dd": round(dd, 4)}


def main():
    U = load("universe.json", None)
    if not U:
        print("Falta data/universe.json")
        return
    D, C = prepare(U)
    stocks = [t for t in C if t not in ("SPY", "QQQ")]
    spy = C["SPY"]
    regime_ok = [(sma(spy, i, 200) or float("inf")) < spy[i] for i in range(len(D))]
    first_day = [i > 0 and D[i][:7] != D[i - 1][:7] for i in range(len(D))]
    last = D[-1]
    y, md = int(last[:4]), last[4:]
    wins = {}
    for key, label, yrs in (("1a", "1 año", 1), ("2a", "2 años", 2)):
        a = f"{y - yrs}{md}"
        s = next(i for i in range(len(D)) if D[i] >= a)
        s = max(s, LB["12m"])
        univ = [t for t in stocks if C[t][s - LB["12m"]] is not None]
        rows = []
        for n in (5, 10, 20):
            for kind in SCORES:
                for regime in REGIMES:
                    k = f"n{n}_{kind}_{regime}"
                    eq, ev, hold, cash = simulate(D, C, univ, s, n, kind, regime, regime_ok, first_day)
                    row = {"k": k, "n": n, "score": kind, "regime": regime, **stats(eq), "cash": round(cash, 3),
                           "trades": sum(len(e["buy"]) + len(e["sell"]) for e in ev), "eq": eq}
                    if k == DEFAULT:
                        row["events"] = ev
                    rows.append(row)
        bh = {}
        for t in ("SPY", "QQQ"):
            eq = [round(C[t][i] / C[t][s], 4) for i in range(s, len(D))]
            bh[t] = {**stats(eq), "eq": eq}
        ew = [round(sum(C[t][i] / C[t][s] for t in univ) / len(univ), 4) for i in range(s, len(D))]
        bh["EW"] = {**stats(ew), "eq": ew}
        per = sorted(((round(C[t][-1] / C[t][s] - 1, 4), t) for t in univ), reverse=True)
        bh["beat_spy"] = sum(1 for r, _ in per if r > bh["SPY"]["ret"])
        bh["n"] = len(per)
        wins[key] = {"label": label, "from": D[s], "to": last, "dates": D[s:], "universe": len(univ), "rows": rows, "bh": bh}

    # Estado actual de la regla propuesta: se toma la simulación de 2 años, que llega hasta hoy
    dflt = next(r for r in wins["2a"]["rows"] if r["k"] == DEFAULT)
    ev = dflt["events"]
    i = len(D) - 1
    rk = ranking(C, stocks, i, "mix")
    pos = {t: k + 1 for k, (_, t) in enumerate(rk)}
    holding = ev[-1]["hold"] if ev else []
    entry = {}
    for e in ev:
        for t in e["buy"]:
            entry[t] = e["d"]
    def ret_since(t):
        j = D.index(entry[t]) if t in entry else None
        return round(C[t][i] / C[t][j] - 1, 4) if j is not None else None
    s200 = sma(spy, i, 200)
    top10 = [t for _, t in rk[:10]]
    state = {
        "date": last,
        "regime": {"ok": regime_ok[i], "spy": round(spy[i], 2), "sma200": round(s200, 2), "dist": round(spy[i] / s200 - 1, 4)},
        "holding": [{"t": t, "since": entry.get(t), "ret": ret_since(t), "rank": pos.get(t),
                     "score": round(dict((x, v) for v, x in rk).get(t, 0), 4)} for t in holding],
        "top": [{"t": t, "rank": k + 1, "score": round(v, 4), "r3": round(C[t][i] / C[t][i - 63] - 1, 4),
                 "r6": round(C[t][i] / C[t][i - 126] - 1, 4), "r12": round(C[t][i] / C[t][i - 252] - 1, 4)}
                for k, (v, t) in enumerate(rk[:25])],
        # si el mes cambiara hoy: quiénes entrarían y quiénes saldrían
        "preview": {"buy": [t for t in top10 if t not in holding], "sell": [t for t in holding if t not in top10]},
        "next": "primer día hábil del próximo mes",
    }
    out = {"generated": datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M"), "default": DEFAULT,
           "scores": SCORES, "regimes": REGIMES, "nasdaq100": U.get("nasdaq100", []), "sp500": U.get("sp500", []),
           "universe": len(stocks), "state": state, "events": ev[-40:], "windows": wins}
    with open(os.path.join(DATA, "momentum.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Momentum: {len(stocks)} acciones, {len(ev)} rebalanceos en 2 años")
    log_alerts(ev, last)


def log_alerts(ev, last):
    """Registra en el buzón las compras y ventas de la regla. Las de días anteriores (hasta 60 días) entran
    sin aviso; las del cierre de hoy se agregan solo después del cierre y también van por correo."""
    now = datetime.now(ZoneInfo("America/New_York"))
    closed = now.weekday() < 5 and (now.hour, now.minute) >= (16, 15) and now.date().isoformat() == last
    since = (datetime.fromisoformat(last) - timedelta(days=60)).date().isoformat()
    log = load("alerts_log.json", [])
    keys = {a["key"] for a in log}
    why = {"mes": "rebalanceo mensual", "mercado": "filtro de mercado (SPY y su media de 200 días)", "inicio": "inicio"}
    lines, added = [], 0
    for e in ev:
        if e["d"] < since or e["why"] == "inicio" or (e["d"] == last and not closed):
            continue
        for a, ts in (("buy", e["buy"]), ("sell", e["sell"])):
            for t in ts:
                key = f"{e['d']}|{t}|momentum|{a}"
                if key in keys:
                    continue
                keys.add(key)
                added += 1
                txt = f"{'entra a' if a == 'buy' else 'sale de'} la cartera por {why[e['why']]}"
                log.append({"key": key, "d": e["d"], "t": t, "src": "momentum", "a": a, "txt": txt})
                if e["d"] == last:
                    lines.append(f"- **{t}** · Momentum top 10: **{'COMPRA' if a == 'buy' else 'VENTA'}** en la próxima apertura ({why[e['why']]}).")
    if added:
        with open(os.path.join(DATA, "alerts_log.json"), "w") as f:
            json.dump(log[-3000:], f, separators=(",", ":"))
    if lines:
        path = os.path.join(DATA, "..", "alertas.md")
        head = "" if os.path.exists(path) else f"Señales al cierre del {last}:\n\n"
        with open(path, "a") as f:
            f.write(head + "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
