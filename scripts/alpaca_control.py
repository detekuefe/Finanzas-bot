"""Pausa o reanuda la réplica en Alpaca paper. Lo ejecuta la acción "Alpaca paper: pausar o reanudar".

- vender_y_pausar: cancela las órdenes pendientes, vende todas las posiciones a mercado (si el mercado está
  cerrado, la venta queda en cola para la apertura) y pausa: el script diario no vuelve a comprar.
- pausar: deja las posiciones como están y deja de enviar órdenes.
- reanudar: quita la pausa. En la próxima corrida de cierre la cuenta vuelve a seguir a la regla
  (si está en efectivo, arma la cartera completa).

Guarda el estado en data/alpaca_control.json y la página #paper lo muestra.
"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from alpaca_paper import CONTROL, OUT, Paper, load

ACTIONS = ("vender_y_pausar", "pausar", "reanudar")


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if action not in ACTIONS:
        sys.exit(f"Acción desconocida: {action!r}. Usa una de {', '.join(ACTIONS)}.")
    key, secret = os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY")
    if not (key and secret):
        sys.exit("Faltan los secrets ALPACA_KEY_ID y ALPACA_SECRET_KEY.")
    api = Paper(key, secret)
    now = datetime.now(ZoneInfo("America/Santiago")).strftime("%Y-%m-%d %H:%M")

    if action == "vender_y_pausar":
        api.cancel_open()
        closed = api.close_all() or []
        print(f"Órdenes pendientes canceladas; {len(closed)} posiciones enviadas a vender.")
    ctl = {"paused": action != "reanudar", "action": action, "since": now}
    with open(CONTROL, "w") as f:
        json.dump(ctl, f, separators=(",", ":"))
    print({"vender_y_pausar": "Vendido todo y pausado.", "pausar": "Pausado sin vender.",
           "reanudar": "Reanudado: la próxima corrida de cierre vuelve a seguir a la regla."}[action])

    log = load(OUT, None)
    if log is not None:  # deja la página al día con las órdenes y posiciones nuevas
        log["positions"] = api.positions_detail()
        log["orders"] = api.recent_orders()
        log["updated"] = now
        with open(OUT, "w") as f:
            json.dump(log, f, separators=(",", ":"))


if __name__ == "__main__":
    main()
