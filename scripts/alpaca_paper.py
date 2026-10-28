"""Replica la estrategia de momentum (top 10, siempre invertida) en una cuenta
de simulación (paper) de Alpaca.

Cada día hábil, después de que scripts/momentum.py calcula el estado al cierre:
- toma las acciones que la regla tiene en cartera hoy (data/momentum.json → state.holding);
- vende las que la cuenta tiene y la regla no, y compra las que faltan;
- el día de un rebalanceo de la regla (el primer día hábil de cada mes), lleva todo a partes iguales.
Las órdenes son a mercado y, como se envían con el mercado cerrado, se ejecutan en la próxima apertura,
igual que supone el backtest.

Solo usa el servidor de simulación de Alpaca. No hay forma de apuntarlo a una cuenta real.
Claves: variables de entorno ALPACA_KEY_ID y ALPACA_SECRET_KEY (secrets del repositorio).
Sin claves, o con --dry-run, solo muestra las órdenes que enviaría.

Escribe data/alpaca_paper.json con el valor diario de la cuenta y las órdenes enviadas.

Venta por caída (--stop, corre cada 15 minutos): entre 15 minutos después de la apertura y 10 minutos antes
del cierre de Nueva York, si una acción de la cuenta va -10% o peor desde el cierre anterior, se vende solo
esa y se compra con lo obtenido la mejor del ranking de la regla que no esté en la cuenta. La vendida no
vuelve hasta el rebalanceo del mes; mientras tanto la corrida de cierre trata a la reemplazante como si
fuera la de la regla. El registro queda en data/alpaca_stops.json.
"""
import argparse
import json
import os
import sys
import time
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
STOPS = os.path.join(DATA, "alpaca_stops.json")
STOP = 0.10  # caída en el día, desde el cierre anterior, que dispara la venta
STOP_FROM, STOP_TO = (9, 45), (15, 50)  # hora de Nueva York: 15 min después de la apertura y 10 min antes del cierre


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
                 "pl": round(float(p["unrealized_pl"]), 2), "plpc": round(float(p["unrealized_plpc"]), 4),
                 "day": round(float(p.get("change_today") or 0), 4)}
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

    def clock(self):
        return self.call("GET", "/v2/clock")

    def get_order(self, oid):
        return self.call("GET", f"/v2/orders/{oid}")

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


def stops_state(st):
    """Reemplazos vigentes por venta por caída. Se reinician cuando la regla pasa a un mes nuevo (rebalanceo)."""
    s = load(STOPS, {"log": []})
    month = st["date"][:7]
    if s.get("month") != month:
        s.update({"month": month, "subs": {}, "banned": []})
    return s


def apply_subs(target, s):
    """Cartera de la regla con las vendidas por caída cambiadas por sus reemplazantes."""
    return [s["subs"].get(t, t) for t in target]


def run_stops(dry=False):
    """Vende la acción que cae -10% o más en el día y compra la siguiente del ranking. Solo en horario regular."""
    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        print("Sin claves de Alpaca: no se revisan caídas.")
        return
    now = datetime.now(ZoneInfo("America/New_York"))
    if not (STOP_FROM <= (now.hour, now.minute) < STOP_TO):
        print(f"Fuera de la ventana de venta por caída ({now:%H:%M} de Nueva York).")
        return
    if load(CONTROL, {}).get("paused"):
        print("Pausado: no se revisan caídas.")
        return
    m = load(os.path.join(DATA, "momentum.json"), None)
    if not m:
        return
    api = Paper(key, secret)
    if not api.clock().get("is_open"):
        print("El mercado está cerrado hoy.")
        return
    st, s = m["state"], stops_state(m["state"])
    today = now.date().isoformat()
    bought_today = {e["bought"] for e in s["log"] if e["d"] == today and e.get("bought")}
    pos = api.positions_detail()
    held = {p["t"] for p in pos} | set(apply_subs([to_alpaca(h["t"]) for h in st["holding"]], s))
    hit = [p for p in pos if p["day"] <= -STOP and p["t"] not in bought_today and p["t"] not in s["banned"]]
    if not hit:
        print("Sin caídas de -10% o más en la cuenta.")
    for p in hit:
        cand = next((c for c in (to_alpaca(r["t"]) for r in st.get("top", []))
                     if c not in held and c not in s["banned"] and c != p["t"]), None)
        print(f"  {p['t']} va {p['day'] * 100:.1f}% en el día: se vende y entra {cand or 'nadie (sin candidato)'}")
        if dry:
            continue
        entry = {"d": today, "time": now.strftime("%H:%M"), "sold": p["t"], "day": p["day"], "price": p["price"]}
        try:
            o = api.close(p["t"])
            for _ in range(20):  # a mercado y en horario regular se ejecuta en segundos
                o = api.get_order(o["id"])
                if o["status"] == "filled":
                    break
                time.sleep(3)
            got = float(o.get("filled_qty") or 0) * float(o.get("filled_avg_price") or 0) or p["value"]
            entry["usd"] = round(got, 2)
        except RuntimeError as e:
            entry["error"] = str(e)[:300]
            s["log"].append(entry)
            continue
        s["banned"].append(p["t"])
        orig = next((k for k, v in s["subs"].items() if v == p["t"]), p["t"])  # si ya era reemplazante, hereda su lugar
        if cand:
            s["subs"][orig] = cand
            held.add(cand)
            usd = min(got, float(api.account()["cash"]))
            if usd >= MIN_ORDER:
                try:
                    api.order(cand, "buy", usd)
                    entry.update({"bought": cand, "buy_usd": round(usd, 2)})
                except RuntimeError as e:
                    entry["error"] = str(e)[:300]
        else:
            s["subs"].pop(orig, None)
        held.discard(p["t"])
        s["log"].append(entry)
    if not dry:
        with open(STOPS, "w") as f:
            json.dump(s, f, separators=(",", ":"))


def refresh_status():
    """Actualiza en el registro el valor, las posiciones y las órdenes de la cuenta, sin enviar órdenes ni
    agregar un punto al historial (eso lo hace la corrida de cierre). Corre cada 15 minutos para que la página
    muestre las ejecuciones y el valor del día."""
    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        return
    api = Paper(key, secret)
    acct = api.account()
    log = load(OUT, {"history": []})
    log["updated"] = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M")
    log["equity"], log["cash"] = round(float(acct["equity"]), 2), round(float(acct["cash"]), 2)
    log["last_equity"] = round(float(acct.get("last_equity") or 0), 2) or None  # valor al cierre anterior
    log["positions"] = api.positions_detail()
    log["orders"] = api.recent_orders()
    with open(OUT, "w") as f:
        json.dump(log, f, separators=(",", ":"))
    print(f"Estado de la cuenta: valor {log['equity']:,.2f} · {len(log['positions'])} posiciones.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="muestra las órdenes sin enviarlas")
    ap.add_argument("--force", action="store_true", help="opera aunque los datos no sean de hoy")
    ap.add_argument("--status", action="store_true", help="solo actualiza valor, posiciones y órdenes; no opera")
    ap.add_argument("--stop", action="store_true", help="venta por caída de -10% en el día (cada 15 minutos)")
    args = ap.parse_args()
    if args.stop:
        run_stops(args.dry_run)
        return
    if args.status:
        refresh_status()
        return

    m = load(os.path.join(DATA, "momentum.json"), None)
    if not m:
        sys.exit("Falta data/momentum.json; corre antes scripts/momentum.py")
    st = m["state"]
    now = datetime.now(ZoneInfo("America/New_York"))
    today = now.date().isoformat()
    if not args.force:
        why = None
        if st["date"] != today:
            why = f"El estado de la regla es del {st['date']} y hoy es {today} (aún no cierra, feriado o datos atrasados)"
        elif (now.hour, now.minute) < (16, 15):
            why = "El mercado no ha cerrado: la regla decide con el cierre"
        if why:
            print(f"{why}: no se opera, solo se actualiza el estado de la cuenta.")
            refresh_status()
            return
    stops = stops_state(st)
    target = apply_subs([to_alpaca(h["t"]) for h in st["holding"]], stops)
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

    print(f"Regla al {st['date']}: cartera {', '.join(target) or 'ninguna'}{' · día de rebalanceo' if rebalance else ''}")
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
    if stops.get("subs") or os.path.exists(STOPS):  # guarda el reinicio de mes
        with open(STOPS, "w") as f:
            json.dump(stops, f, separators=(",", ":"))

if __name__ == "__main__":
    main()
