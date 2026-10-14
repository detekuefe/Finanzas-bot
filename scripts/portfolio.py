"""Estrategias de cartera con rebalanceo mensual sobre los activos de la app.

Compara contra comprar y mantener (cada activo, cartera igual peso y S&P 500):
- Rotación por momentum relativo: cada fin de mes compra los N activos con mejor retorno.
- La misma con filtro absoluto (solo activos con retorno de 12 meses positivo) y con filtro de
  régimen (solo invierte si el S&P 500 cierra sobre su media de 10 meses).
- Momentum dual (Antonacci): el mejor índice entre S&P 500, Nasdaq y ACWI por 12 meses; efectivo si es negativo.
- Tendencia de Faber: cada activo pesa 1/N y se mantiene solo si cierra el mes sobre su media de 10 meses.

- Repite la rotación y Faber usando solo índices (S&P 500, Nasdaq, ACWI, QQQ), sin sesgo de selección.
- Reversión de Connors con RSI(2) en velas diarias sobre los índices (2 años de datos).

Usa cierres de fin de mes tomados de las velas semanales (10 años).
Escribe data/portfolio.json. Uso: python scripts/portfolio.py
"""
import json
import math
import os
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
COST = 0.0005  # por lado, sobre lo que se compra o vende en cada rebalanceo
INDEXES = ["SP500", "NASDAQ", "ACWI"]


def load_monthly(kind):
    """Cierre del último día disponible de cada mes, por activo: {ticker: {"YYYY-MM": close}}."""
    with open(os.path.join(DATA, "summary.json")) as f:
        tickers = list(json.load(f)["tickers"])
    out = {}
    for t in tickers:
        with open(os.path.join(DATA, f"{t}.json")) as f:
            rows = json.load(f)[kind]
        m = {}
        for r in rows:
            if r[4] is not None:
                m[r[0][:7]] = r[4]
        out[t] = m
    return out


def months_between(a, b):
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + mb - ma


def simulate(P, months, pick):
    """P: precios mensuales; pick(i) -> {ticker: peso} decidido con datos hasta el mes i, se mantiene en i+1.
    Devuelve el valor de la cartera al cierre de cada mes desde months[0], y las posiciones de cada mes."""
    val, w, eq, hold = 1.0, {}, [1.0], []
    for i in range(len(months) - 1):
        new = pick(i)
        turnover = sum(abs(new.get(t, 0) - w.get(t, 0)) for t in set(new) | set(w))
        val *= 1 - turnover * COST
        m0, m1 = months[i], months[i + 1]
        r = sum(wt * (P[t][m1] / P[t][m0] - 1) for t, wt in new.items() if m1 in P[t] and m0 in P[t])
        val *= 1 + r
        # los pesos derivan con los precios hasta el próximo rebalanceo
        grown = {t: wt * (P[t][m1] / P[t][m0]) for t, wt in new.items() if m1 in P[t] and m0 in P[t]}
        tot = sum(grown.values()) + (1 - sum(new.values()))
        w = {t: v / tot for t, v in grown.items()} if tot else {}
        eq.append(val)
        hold.append(sorted(new, key=lambda t: -new[t]))
    return eq, hold


def ret(P, t, months, i, k):
    """Retorno de k meses del activo t al mes i, o None si no hay datos."""
    if i - k < 0:
        return None
    a, b = P[t].get(months[i - k]), P[t].get(months[i])
    return b / a - 1 if a and b else None


def sma(P, t, months, i, k):
    xs = [P[t].get(months[j]) for j in range(i - k + 1, i + 1)] if i - k + 1 >= 0 else []
    return sum(xs) / k if xs and all(xs) else None


IDX_UNIVERSE = ["SP500", "NASDAQ", "ACWI", "QQQ"]


def strategies(P, months, universe, only_idx=False):
    def mom_score(t, i, lbs):
        rs = [ret(P, t, months, i, k) for k in lbs]
        return None if any(r is None for r in rs) else sum(rs) / len(rs)

    def rotation(n, lbs, absolute=False, regime=False):
        def pick(i):
            if regime:
                s = sma(P, "SP500", months, i, 10)
                if s is None or P["SP500"][months[i]] < s:
                    return {}
            cands = [(mom_score(t, i, lbs), t) for t in universe if months[i] in P[t]]
            cands = sorted([c for c in cands if c[0] is not None], reverse=True)[:n]
            if absolute:
                cands = [c for c in cands if (ret(P, c[1], months, i, 12) or -1) > 0]
            return {t: 1 / n for _, t in cands}  # la parte no invertida queda en efectivo
        return pick

    def dual(i):
        cands = [(ret(P, t, months, i, 12), t) for t in INDEXES]
        cands = [c for c in cands if c[0] is not None]
        if not cands:
            return {}
        best = max(cands)
        return {best[1]: 1.0} if best[0] > 0 else {}

    def faber(i):
        avail = [t for t in universe if months[i] in P[t] and sma(P, t, months, i, 10) is not None]
        if not avail:
            return {}
        return {t: 1 / len(avail) for t in avail if P[t][months[i]] > sma(P, t, months, i, 10)}

    def ew(i):
        avail = [t for t in universe if months[i] in P[t]]
        return {t: 1 / len(avail) for t in avail}

    if only_idx:
        # sin sesgo de selección: solo índices amplios, que nadie elige mirando hacia atrás
        out = [("ix_ew", "Índices igual peso (rebalanceo mensual)", "Solo índices", ew)]
        for n in (1, 2):
            for lbs, ln in (((3,), "3 meses"), ((6,), "6 meses"), ((12,), "12 meses"), ((3, 6, 12), "promedio 3/6/12 meses")):
                base = f"Índices: los {n} mejores por retorno de {ln}" if n > 1 else f"Índices: el mejor por retorno de {ln}"
                k = f"ix_rot{n}_{'_'.join(map(str, lbs))}"
                out.append((k, base, "Solo índices", rotation(n, lbs)))
                out.append((k + "_abs", base + " + solo si 12 meses > 0", "Solo índices", rotation(n, lbs, absolute=True)))
                out.append((k + "_reg", base + " + S&P 500 sobre su media de 10 meses", "Solo índices", rotation(n, lbs, regime=True)))
        out.append(("ix_dual", "Momentum dual: el mejor entre S&P 500, Nasdaq y ACWI (12 meses), efectivo si es negativo", "Solo índices", dual))
        out.append(("ix_faber", "Faber en índices: cada índice solo si cierra el mes sobre su media de 10 meses", "Solo índices", faber))
        out.append(("ix_sp_reg", "S&P 500 solo si cierra el mes sobre su media de 10 meses", "Solo índices",
                    lambda i: {"SP500": 1.0} if (sma(P, "SP500", months, i, 10) or 1e18) < P["SP500"][months[i]] else {}))
        return out
    out = [("ew", "Cartera igual peso (rebalanceo mensual)", "Referencia", ew)]
    for n in (1, 2, 3, 5):
        for lbs, ln in (((3,), "3 meses"), ((6,), "6 meses"), ((12,), "12 meses"), ((3, 6, 12), "promedio 3/6/12 meses")):
            base = f"Rotación: los {n} mejores por retorno de {ln}" if n > 1 else f"Rotación: el mejor por retorno de {ln}"
            k = f"rot{n}_{'_'.join(map(str, lbs))}"
            out.append((k, base, "Rotación por momentum", rotation(n, lbs)))
            out.append((k + "_abs", base + " + solo si 12 meses > 0", "Rotación por momentum", rotation(n, lbs, absolute=True)))
            out.append((k + "_reg", base + " + S&P 500 sobre su media de 10 meses", "Rotación por momentum", rotation(n, lbs, regime=True)))
    out.append(("dual", "Momentum dual: el mejor entre S&P 500, Nasdaq y ACWI (12 meses), efectivo si es negativo", "Momentum dual", dual))
    out.append(("faber", "Faber: cada activo solo si cierra el mes sobre su media de 10 meses", "Tendencia", faber))
    return out


def stats(eq, months):
    n = len(eq) - 1
    peak, dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        dd = min(dd, v / peak - 1)
    total = eq[-1] / eq[0] - 1
    cagr = (eq[-1] / eq[0]) ** (12 / n) - 1 if n else 0.0
    rets = [eq[i + 1] / eq[i] - 1 for i in range(n)]
    mu = sum(rets) / n if n else 0
    sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / (n - 1)) if n > 1 else 0
    return {"ret": round(total, 4), "cagr": round(cagr, 4), "dd": round(dd, 4),
            "sharpe": round(mu / sd * math.sqrt(12), 2) if sd else None}


def run(kind, windows):
    P = load_monthly(kind)
    allm = sorted({m for t in P for m in P[t]})
    res = {"months": allm, "windows": {}}
    for key, label, a, b in windows:
        # mes de partida: el último mes completo antes del inicio pedido; los indicadores usan la historia previa
        months = [m for m in allm if a <= m <= b]
        i0 = allm.index(months[0]) - 1 if allm.index(months[0]) > 0 else 0
        ms = allm[i0:allm.index(months[-1]) + 1]
        universe = [t for t in P if ms[0] in P[t] and ms[-1] in P[t]]
        subP = P
        rows = []
        idxu = [t for t in IDX_UNIVERSE if t in universe]
        for k, name, group, fn in strategies(subP, allm, universe) + strategies(subP, allm, idxu, only_idx=True):
            off = allm.index(ms[0])
            eq, hold = simulate(subP, allm[off:off + len(ms)], lambda i, fn=fn: fn(i + off))
            now = fn(off + len(ms) - 1)  # lo que tocaría tener durante el mes siguiente al último cierre
            rows.append({"k": k, "name": name, "group": group, **stats(eq, ms), "eq": [round(v, 4) for v in eq],
                         "hold": hold[-1] if hold else [], "now": sorted(now, key=lambda t: -now[t])})
        bh = {t: round(P[t][ms[-1]] / P[t][ms[0]] - 1, 4) for t in universe}
        bhstats = {}
        for t in ("SP500", "NASDAQ", "ACWI", "QQQ"):
            if t in universe:
                eq = [P[t][m] / P[t][ms[0]] for m in ms]
                bhstats[t] = {**stats(eq, ms), "eq": [round(v, 4) for v in eq]}
        res["windows"][key] = {"label": label, "from": ms[0], "to": ms[-1], "months": ms, "universe": universe, "rows": rows, "bh": bh, "bhIdx": bhstats}
    return res


def rsi_wilder(c, n):
    out = [None] * len(c)
    g = l = 0.0
    for i in range(1, len(c)):
        d = c[i] - c[i - 1]
        up, dn = max(d, 0), max(-d, 0)
        if i <= n:
            g += up / n
            l += dn / n
            if i < n:
                continue
        else:
            g = (g * (n - 1) + up) / n
            l = (l * (n - 1) + dn) / n
        out[i] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    return out


def connors(tickers, windows):
    """Reversión a la media de Connors en velas diarias: compra al cierre si RSI(2) < umbral y el precio está sobre
    su media de 200 días; vende al cierre cuando el precio supera su media de 5 días."""
    res = {}
    for t in tickers:
        with open(os.path.join(DATA, f"{t}.json")) as f:
            rows = [r for r in json.load(f)["daily"] if r[4] is not None]
        d = [r[0] for r in rows]
        c = [r[4] for r in rows]
        r2 = rsi_wilder(c, 2)
        s200 = [None if i < 199 else sum(c[i - 199:i + 1]) / 200 for i in range(len(c))]
        s5 = [None if i < 4 else sum(c[i - 4:i + 1]) / 5 for i in range(len(c))]
        res[t] = {}
        for key, a in windows:
            i0 = next((i for i in range(len(d)) if d[i] >= a and s200[i] is not None), None)
            if i0 is None:
                continue
            out = {}
            for thr in (10, 5):
                val, pos, eq, n, inside, peak, dd = 1.0, False, [1.0], 0, 0, 1.0, 0.0
                for i in range(i0 + 1, len(c)):
                    if pos:
                        val *= c[i] / c[i - 1]
                        inside += 1
                    if not pos and r2[i] is not None and r2[i] < thr and c[i] > s200[i]:
                        pos, n, val = True, n + 1, val * (1 - COST)
                    elif pos and c[i] > s5[i]:
                        pos, val = False, val * (1 - COST)
                    peak, dd = max(peak, val), min(dd, val / peak - 1)
                    eq.append(round(val, 4))
                out[f"rsi{thr}"] = {"ret": round(val - 1, 4), "dd": round(dd, 4), "trades": n,
                                    "expo": round(inside / (len(c) - i0 - 1), 3), "eq": eq}
            bh = [x / c[i0] for x in c[i0:]]
            peak, dd = 1.0, 0.0
            for v in bh:
                peak, dd = max(peak, v), min(dd, v / peak - 1)
            out["bh"] = {"ret": round(bh[-1] - 1, 4), "dd": round(dd, 4), "eq": [round(v, 4) for v in bh]}
            out["from"], out["to"], out["dates"] = d[i0], d[-1], d[i0:]
            res[t][key] = out
    return res


def main():
    today = date.today().strftime("%Y-%m")
    with open(os.path.join(DATA, "QQQ.json")) as f:
        q = json.load(f)
    last_w = q["weekly"][-1][0][:7]
    y = int(last_w[:4])
    weekly = [("10a", "10 años", f"{y - 10}{last_w[4:]}", last_w), ("5a", "5 años", f"{y - 5}{last_w[4:]}", last_w),
              ("3a", "3 años", f"{y - 3}{last_w[4:]}", last_w), ("2a", "2 años", f"{y - 2}{last_w[4:]}", last_w),
              ("1a", "1 año", f"{y - 1}{last_w[4:]}", last_w),
              ("2020", "Año 2020", "2020-01", "2020-12"), ("2022", "Año 2022", "2022-01", "2022-12")]
    last_d = q["daily"][-1][0]
    yd, md, dd = int(last_d[:4]), int(last_d[5:7]), last_d[8:]
    back = lambda n: f"{yd - (n - md + 12) // 12 if n >= md else yd}-{(md - n - 1) % 12 + 1:02d}-{dd}"
    cwin = [("all", "0000"), ("12m", back(12)), ("6m", back(6))]
    out = {"generated": today, "weekly": run("weekly", weekly), "connors": connors(IDX_UNIVERSE, cwin)}
    with open(os.path.join(DATA, "portfolio.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
