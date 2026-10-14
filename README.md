# Finanzas bot

Plataforma para seguir los activos de la planilla `Ensayo.xlsx`:
- una página de resumen con el desempeño de los activos (los 19 de la planilla más ACWI, S&P 500 y Nasdaq), en dólares o en pesos,
- una ficha por activo con gráficos intradía (velas de 5 minutos con pivotes PP, R1/S1, R2/S2 y CPR), diarios y semanales (SMA, Bollinger, RSI, MACD).

## Cómo funciona

| Pieza | Qué hace |
|---|---|
| `index.html` | La app. GitHub Pages la publica tal cual. Incluye el Laboratorio (`#lab`), que calcula indicadores y backtests en el navegador con los mismos datos. |
| `scripts/fetch_data.py` | Descarga precios de Yahoo Finance (`yfinance`) y los guarda en `data/`. |
| `.github/workflows/update-data.yml` | Ejecuta el script cada 5 minutos de lunes a viernes, en horario de mercado, y guarda los cambios. |
| `data/<TICKER>.json` | Velas diarias (2 años, se acumulan) y semanales (10 años). |
| `data/intra/<TICKER>.json` | Velas de 5 minutos por sesión, con premarket. Yahoo entrega 60 días; el repositorio los va acumulando. |
| `data/summary.json` | Último precio y cierres recientes de cada activo, más VIX, tasa a 10 años, Brent y dólar en pesos. |
| `data/USDCLP.json` | Dólar en pesos chilenos, diario (2 años) y semanal (10 años), para medir rentabilidades en pesos. |
| `scripts/strategies.py` | Calcula las estrategias Ichimoku y EMA 9/18 vs SMA 30, el backtest y el estado de cada activo. Al cierre abre un issue con las señales nuevas (GitHub te avisa por correo). |
| `data/signals.json`, `data/strat/` | Estado, backtest y series de cada estrategia. |
| `scripts/ranking.js` y `scripts/portfolio.py` → `data/ranking.json` | Prueba unas 100 combinaciones del Laboratorio en todos los activos (diario, 6 a 24 meses) y arma el ranking de la página `#ranking`. Corre una vez al día. |
| `data/planilla.json` | Datos de la planilla original (precios anotados a mano de mayo a octubre de 2026). |

## Puesta en marcha (una sola vez)

1. **Settings → Pages**: en *Source* elige *GitHub Actions*. La acción publica la página después de cada descarga. (Con *Deploy from a branch* también funciona, pero GitHub limita esas publicaciones a unas 10 por hora.)
2. **Actions → Actualizar datos → Run workflow** para la primera descarga.
3. Abre la dirección que muestra Pages (`https://detekuefe.github.io/finanzas-bot/`).

## Agregar o quitar activos

Edita la lista `TICKERS` en `scripts/fetch_data.py` y `ALL` en `index.html`.
