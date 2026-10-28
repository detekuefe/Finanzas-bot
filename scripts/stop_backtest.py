"""Backtest de la regla de venta por caída en el día sobre la estrategia de momentum (top 10, mensual).

Compara la regla sin venta por caída con dos versiones:
- al cierre: si una acción cierra el día con -X% o peor desde el cierre anterior, se vende y entra la
  siguiente del ranking que no esté en cartera; la vendida no vuelve hasta el rebalanceo del mes;
- durante el día: si en el día toca -X% (con velas diarias: el mínimo), se vende a -X%, o a la apertura
  si ya abrió más abajo; la reemplazante se compra al cierre de ese día.
Usa data/universe_long.json para el ranking y descarga de Yahoo apertura, máximo y mínimo.
Solo imprime resultados; no cambia nada del bot.
"""
import json
import os
import sys

import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from momentum import COST, LB, prepare, ranking  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def main():
    U = json.load(open(os.path.join(DATA, "universe_long.json")))
    D, C = prepare(U)
    stocks = [t for t in C if t not in ("SPY", "QQQ")]
    df = yf.download(stocks, start=D[0], interval="1d", auto_adjust=True, progress=False, threads=True)
    idx = {d.strftime("%Y-%m-%d"): k for k, d in enumerate(df.index)}
    O, L = {}, {}
    for t in stocks:
        o, lo = df["Open"][t].tolist(), df["Low"][t].tolist()
        O[t] = [o[idx[d]] if d in idx else None for d in D]
        L[t] = [lo[idx[d]] if d in idx else None for d in D]
    first = [i > 0 and D[i][:7] != D[i - 1][:7] for i in range(len(D))]

    def sim(s, e, x, mode):
        val, w, eq, n, banned = 1.0, {}, [1.0], 0, set()

        def reb(i):
            nonlocal val, w
            tg = [t for _, t in ranking(C, stocks, i, "mix")[:10]]
            new = {t: 0.1 for t in tg}
            val *= 1 - sum(abs(new.get(t, 0) - w.get(t, 0)) for t in set(new) | set(w)) * COST
            w = new

        reb(s)
        for i in range(s + 1, e + 1):
            g, out = {}, []
            for t, wt in w.items():
                p0, c = C[t][i - 1], C[t][i]
                lvl = p0 * (1 - x)
                if mode == "dia" and O[t][i] and L[t][i] and L[t][i] <= lvl:
                    fill = min(O[t][i], lvl)  # el ajuste de Yahoo puede diferir levemente del de los cierres
                    g[t] = wt * fill / p0
                    out.append(t)
                elif mode == "cierre" and c / p0 - 1 <= -x:
                    g[t] = wt * c / p0
                    out.append(t)
                else:
                    g[t] = wt * c / p0
            tot = sum(g.values())
            val *= tot
            w = {t: v / tot for t, v in g.items()}
            if first[i]:
                banned = set()
                reb(i)
                out = []
            for t in out:
                n += 1
                wt = w.pop(t)
                banned.add(t)
                cand = next(y for _, y in ranking(C, stocks, i, "mix") if y not in w and y not in banned)
                w[cand] = wt
                val *= 1 - 2 * wt * COST
            eq.append(val)
        pk, dd = 1.0, 0.0
        for v in eq:
            pk = max(pk, v)
            dd = min(dd, v / pk - 1)
        return eq[-1] - 1, dd, n

    per = [("2018-2026", "2018-01", None), ("2022-2026", "2022-01", None), ("Últimos 2 años", "2024-10", None),
           ("Solo 2022", "2022-01", "2022-12-31"), ("Solo 2025", "2025-01", "2025-12-31")]
    res = []
    for lab, a, b in per:
        s = max(next(i for i in range(len(D)) if D[i] >= a), LB["12m"])
        e = max(i for i in range(len(D)) if b is None or D[i] <= b)
        row = {"periodo": lab, "desde": D[s], "hasta": D[e]}
        for x, mode in ((0, "no"), (0.10, "cierre"), (0.10, "dia"), (0.07, "dia"), (0.15, "dia")):
            r, dd, n = sim(s, e, x, mode)
            row[f"{mode}{int(x * 100)}"] = {"ret": round(r, 4), "dd": round(dd, 4), "ventas": n}
        res.append(row)
        print(json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    main()
