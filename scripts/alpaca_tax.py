"""Ganancias y dividendos de la cuenta Alpaca en pesos chilenos, para la Operación Renta.

- Lee todas las ejecuciones (FILL), dividendos (DIV) y retenciones de EE.UU. (DIVNRA) de la cuenta.
- Asigna cada venta a sus compras por orden de llegada (FIFO) y calcula la ganancia en pesos:
  venta al dólar observado del día de la venta, menos el costo al dólar observado del día de la compra
  reajustado por la variación del IPC entre el mes anterior a la compra y el mes anterior a la venta.
- Dólar observado, IPC y UTM vienen de mindicador.cl (Banco Central / INE / SII). Si no responde, usa el
  dólar de data/USDCLP.json (Yahoo) y deja la venta marcada como aproximada.

Escribe data/alpaca_tax.json agrupado por año comercial (enero a diciembre). La página #paper lo muestra y
estima el Impuesto Global Complementario con los otros ingresos que ingrese el usuario.
Es una estimación de apoyo: la declaración debe revisarla un contador.
"""
import json
import os
from collections import defaultdict, deque
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from alpaca_paper import DATA, Paper, load

OUT = os.path.join(DATA, "alpaca_tax.json")
MINDICADOR = "https://mindicador.cl/api/{}/{}"


def indicator(name, year):
    """{fecha 'YYYY-MM-DD': valor} de mindicador.cl, o {} si no responde."""
    try:
        r = requests.get(MINDICADOR.format(name, year), timeout=20)
        r.raise_for_status()
        return {x["fecha"][:10]: float(x["valor"]) for x in r.json().get("serie", [])}
    except (requests.RequestException, ValueError, KeyError):
        return {}


def on_or_before(series, d):
    """Valor del día d o del último día anterior con dato."""
    ks = [k for k in series if k <= d]
    return series[max(ks)] if ks else None


def activities(api):
    out, token = [], None
    while True:
        params = {"activity_types": "FILL,DIV,DIVNRA", "direction": "asc", "page_size": 100}
        if token:
            params["page_token"] = token
        page = api.call("GET", "/v2/account/activities", params=params) or []
        out += page
        if len(page) < 100:
            return out
        token = page[-1]["id"]


def main():
    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("Sin claves de Alpaca: no se calcula el informe tributario.")
        return
    acts = activities(Paper(key, secret))
    if not acts:
        print("La cuenta todavía no tiene ejecuciones.")
        return

    def day(a):
        return (a.get("transaction_time") or a.get("date") or "")[:10]

    years = sorted({int(day(a)[:4]) for a in acts} | {datetime.now().year})
    first = years[0]
    dolar, ipc, utm = {}, {}, {}
    for y in range(first - 1, years[-1] + 1):
        dolar.update(indicator("dolar", y))
        ipc.update({k[:7]: v for k, v in indicator("ipc", y).items()})  # variación mensual en %
        utm.update({k[:7]: v for k, v in indicator("utm", y).items()})
    yahoo = {r[0]: r[4] for r in load(os.path.join(DATA, "USDCLP.json"), {}).get("daily", [])}

    def fx(d):
        v = on_or_before(dolar, d)
        return (v, True) if v else (on_or_before(yahoo, d), False)

    def ipc_factor(buy, sell):
        """Reajuste del costo: IPC del mes de la compra hasta el mes anterior a la venta (variación entre el
        último día del mes anterior a la compra y el último día del mes anterior a la venta)."""
        f, ok, y, m = 1.0, True, int(buy[:4]), int(buy[5:7])
        while (y, m) < (int(sell[:4]), int(sell[5:7])):
            k = f"{y}-{m:02d}"
            if k in ipc:
                f *= 1 + ipc[k] / 100
            else:
                ok = False  # IPC aún no publicado: queda sin ese mes
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        return f, ok

    lots, sales, divs = defaultdict(deque), [], []
    for a in acts:
        d, t = day(a), a.get("activity_type")
        if t == "FILL":
            sym, qty, px = a["symbol"], float(a["qty"]), float(a["price"])
            if a["side"] == "buy":
                lots[sym].append([qty, px, d])
                continue
            left = qty
            while left > 1e-9 and lots[sym]:
                lot = lots[sym][0]
                q = min(left, lot[0])
                fs, off_s = fx(d)
                fb, off_b = fx(lot[2])
                fac, ipc_ok = ipc_factor(lot[2], d)
                proceeds, cost = q * px * fs, q * lot[1] * fb * fac
                sales.append({"t": sym, "qty": round(q, 6), "buy": lot[2], "sell": d,
                              "buy_px": lot[1], "sell_px": px, "fx_buy": fb, "fx_sell": fs, "ipc": round(fac, 5),
                              "proceeds": round(proceeds), "cost": round(cost), "gain": round(proceeds - cost),
                              "gain_usd": round(q * (px - lot[1]), 2), "approx": not (off_s and off_b and ipc_ok)})
                lot[0] -= q
                left -= q
                if lot[0] <= 1e-9:
                    lots[sym].popleft()
        elif t in ("DIV", "DIVNRA"):
            usd = float(a.get("net_amount") or 0)
            f, official = fx(d)
            divs.append({"t": a.get("symbol"), "d": d, "kind": "div" if t == "DIV" else "ret", "usd": round(usd, 2),
                         "clp": round(usd * f), "approx": not official})

    # compras que siguen en cartera, con el dólar observado de su día (será su costo cuando se vendan)
    held = [{"t": sym, "qty": round(q, 6), "buy": d, "buy_px": px, "fx_buy": fx(d)[0], "official": fx(d)[1]}
            for sym, ls in lots.items() for q, px, d in ls if q > 1e-9]
    out = {"updated": datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M"), "held": held, "years": {}}
    for y in years:
        ys = [s for s in sales if s["sell"][:4] == str(y)]
        yd = [x for x in divs if x["d"][:4] == str(y)]
        dec = utm.get(f"{y}-12") or (utm[max(utm)] if utm else None)
        out["years"][str(y)] = {
            "gain": sum(s["gain"] for s in ys), "gain_usd": round(sum(s["gain_usd"] for s in ys), 2),
            "dividends": sum(x["clp"] for x in yd if x["kind"] == "div"),
            "withheld": -sum(x["clp"] for x in yd if x["kind"] == "ret"),
            "uta": round(dec * 12) if dec else None, "uta_final": f"{y}-12" in utm,
            "sales": ys, "divs": yd}
    with open(OUT, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Informe tributario: {len(sales)} ventas, {len(divs)} movimientos de dividendos.")


if __name__ == "__main__":
    main()
