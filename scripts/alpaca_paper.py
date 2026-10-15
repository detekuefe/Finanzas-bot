"""Replica la estrategia de momentum (top 10, filtro SPY sobre su media de 200 días) en una cuenta
de simulación (paper) de Alpaca.

Cada día hábil, después de que scripts/momentum.py calcula el estado al cierre:
- toma las acciones que la regla tiene en cartera hoy (data/momentum.json → state.holding);
- vende las que la cuenta tiene y la regla no, y compra las que faltan;
- el día de un rebalanceo de la regla (mensual o por el filtro de mercado), lleva todo a partes iguales.
Las órdenes son a mercado y, como se envían con el mercado cerrado, se ejecutan en la próxima apertura,
igual que supone el backtest.

Solo usa el servidor de simulación de Alpaca. No hay forma de apuntarlo a una cuenta real.
Claves: variables de entorno ALPACA_KEY_ID y ALPACA_SECRET_KEY (secrets del repositorio).
Sin claves, o con --dry-run, solo muestra las órdenes que enviaría.

Escribe data/alpaca_paper.json con el valor diario de la cuenta y las órdenes enviadas.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

PAPER_URL = "https://paper-api.alpaca.markets"  # fijo a propósito: nunca la cuenta real
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
OUT = os.path.join(DATA, "alpaca_paper.json")
CONTROL = os.path.join(DATA, "alpaca_control.json")  # pausa manual, ver scripts/alpaca_control.py
N = 10
MIN_ORDER = 1.0  # Alpaca no acepta órdenes fraccionadas de menos de 1 dólar
DRIFT = 0.02  # en un rebalanceo, no toca posiciones que estén a menos de 2% de su peso objetivo


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def to_alpaca(t):
    return t.replace("-", ".")  # BRK-B en Yahoo es BRK.B en Alpaca


class Paper:
    def __init__(self, key, secret):
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def call(self, method, path, **kw):
        r = self.s.request(method, PAPER_URL + path, timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {path}: {r.status_code} {r.text}")
        return r.json() if r.text else None

    def account(self):
        return self.call("GET", "/v2/account")

    def positions(self):
        return {p["symbol"]: float(p["market_value"]) for p in self.call("GET", "/v2/positions")}

    def positions_detail(self):
        return [{"t": p["symbol"], "qty": round(float(p["qty"]), 6), "avg": round(float(p["avg_entry_price"]), 2),
                 "price": round(float(p["current_price"]), 2), "value": round(float(p["market_value"]), 2),
                 "pl": round(float(p["unrealized_pl"]), 2), "plpc": round(float(p["unrealized_plpc"]), 4)}
                for p in self.call("GET", "/v2/positions")]

    def recent_orders(self):
        def num(x):
            return round(float(x), 6) if x not in (None, "") else None
        return [{"d": o["submitted_at"][:10], "t": o["symbol"], "side": o["side"], "usd": num(o.get("notional")),
                 "status": o["status"], "qty": num(o.get("filled_qty")), "price": num(o.get("filled_avg_price")),
                 "filled": (o.get("filled_at") or "")[:10] or None}
                for o in self.call("GET", "/v2/orders", params={"status": "all", "limit": 200, "direction": "desc"})]

    def cancel_open(self):
        self.call("DELETE", "/v2/orders")

    def close_all(self):
        return self.call("DELETE", "/v2/positions", params={"cancel_orders": "true"})

    def close(self, sym):
        return self.call("DELETE", f"/v2/positions/{sym}")

    def order(self, sym, side, notional):
        return self.call("POST", "/v2/orders", json={"symbol": sym, "side": side, "type": "market",
                                                      "time_in_force": "day", "notional": f"{notional:.2f}"})


def plan(target, positions, equity, rebalance):
    """Lista de órdenes (símbolo, 'close' | 'sell' | 'buy', monto) para llevar la cuenta a la regla."""
    goal = equity / N if target else 0
    orders = [(s, "close", v) for s, v in positions.items() if s not in target]
    for s in target:
        have = positions.get(s, 0.0)
        if s not in positions:
            orders.append((s, "buy", goal))
        elif rebalance and abs(have - goal) > DRIFT * goal:
            orders.append((s, "sell" if have > goal else "buy", abs(have - goal)))
    # primero las ventas, para liberar efectivo
    orders.sort(key=lambda o: o[1] == "buy")
    return [o for o in orders if o[1] == "close" or o[2] >= MIN_ORDER]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="muestra las órdenes sin enviarlas")
    ap.add_argument("--force", action="store_true", help="opera aunque los datos no sean de hoy")
    args = ap.parse_args()

    m = load(os.path.join(DATA, "momentum.json"), None)
    if not m:
        sys.exit("Falta data/momentum.json; corre antes scripts/momentum.py")
    st = m["state"]
    now = datetime.now(ZoneInfo("America/New_York"))
    today = now.date().isoformat()
    if not args.force:
        if st["date"] != today:
            print(f"El estado de la regla es del {st['date']} y hoy es {today} (feriado o datos atrasados): no se opera.")
            return
        if (now.hour, now.minute) < (16, 15):
            print("El mercado no ha cerrado: la regla decide con el cierre, no se opera.")
            return
    target = [to_alpaca(h["t"]) for h in st["holding"]]
    ev = m.get("events") or []
    rebalance = bool(ev) and ev[-1]["d"] == st["date"]

    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    dry = args.dry_run or not (key and secret)
    if dry:
        if not (key and secret):
            print("Sin ALPACA_KEY_ID / ALPACA_SECRET_KEY: simulación en seco con una cuenta vacía de 100.000 dólares.")
        api, positions, equity, cash = None, {}, 100000.0, 100000.0
    else:
        api = Paper(key, secret)
        acct = api.account()
        positions, equity, cash = api.positions(), float(acct["equity"]), float(acct["cash"])
    rebalance = rebalance or not positions  # primera vez: arma la cartera completa
    orders = plan(target, positions, equity, rebalance)
    ctl = load(CONTROL, {})
    if ctl.get("paused"):
        print(f"Pausado desde el {ctl.get('since', '?')} ({ctl.get('action', '')}): no se envían órdenes hasta reanudar.")
        orders = []

    print(f"Regla al {st['date']}: filtro de mercado {'activo (en acciones)' if st['regime']['ok'] else 'en efectivo'}; "
          f"cartera {', '.join(target) or 'ninguna'}{' · día de rebalanceo' if rebalance else ''}")
    print(f"Cuenta paper: valor {equity:,.2f} · efectivo {cash:,.2f} · {len(positions)} posiciones")
    for s, side, v in orders:
        print(f"  {'VENDE TODO' if side == 'close' else side.upper():10} {s:6} {v:12,.2f}")
    if not orders and not ctl.get("paused"):
        print("  Sin órdenes: la cuenta ya sigue a la regla.")

    sent = []
    if not dry and not ctl.get("paused"):  # en pausa no toca las ventas que dejó en cola la acción de pánico
        api.cancel_open()  # evita duplicar órdenes si el script corre dos veces antes de la apertura
        for s, side, v in orders:
            try:
                o = api.close(s) if side == "close" else api.order(s, side, v)
                sent.append({"t": s, "side": "sell" if side == "close" else side, "usd": round(v, 2), "id": o.get("id")})
            except RuntimeError as e:
                print(f"  Error con {s}: {e}")
                sent.append({"t": s, "side": side, "usd": round(v, 2), "error": str(e)[:300]})

    if dry:
        return
    # Registro para la página #paper: valor de la cuenta al cierre de cada día junto a SPY y a la regla
    # simulada en el backtest, para comparar desde el primer día; más posiciones y órdenes con su estado.
    u = load(os.path.join(DATA, "universe.json"), {})
    ref = {t: dict(zip(u.get("dates", []), u.get("closes", {}).get(t, []))) for t in ("SPY", "QQQ")}
    w = (m.get("windows") or {}).get("2a") or {}
    dflt = next((r for r in w.get("rows", []) if r["k"] == m.get("default")), None)
    model = dflt["eq"][-1] if dflt and w.get("to") == st["date"] else None
    log = load(OUT, {"history": []})
    log["updated"] = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M")
    log["history"] = [h for h in log["history"] if h["d"] != st["date"]] + [
        {"d": st["date"], "equity": round(equity, 2), "cash": round(cash, 2), "spy": ref["SPY"].get(st["date"]),
         "qqq": ref["QQQ"].get(st["date"]), "model": model}]
    for h in log["history"]:  # días registrados antes de que se guardara QQQ
        h.setdefault("qqq", ref["QQQ"].get(h["d"]))
    log["cash"] = round(cash, 2)
    log["equity"] = round(equity, 2)
    log["positions"] = api.positions_detail()
    log["orders"] = api.recent_orders()
    log["errors"] = [{"d": st["date"], **o} for o in sent if "error" in o]
    with open(OUT, "w") as f:
        json.dump(log, f, separators=(",", ":"))

if __name__ == "__main__":
    main()
