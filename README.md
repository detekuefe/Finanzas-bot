# Finanzas bot

Plataforma para seguir los activos de la planilla `Ensayo.xlsx`:
- una página de resumen con el desempeño de los activos (los 19 de la planilla más ACWI, S&P 500 y Nasdaq), en dólares o en pesos,
- una ficha por activo con gráficos intradía (velas de 5 minutos con pivotes PP, R1/S1, R2/S2 y CPR), diarios y semanales (SMA, Bollinger, RSI, MACD).

## Cómo funciona

| Pieza | Qué hace |
|---|---|
| `index.html` | La app. GitHub Pages la publica tal cual. Incluye el Laboratorio (`#lab`), que calcula indicadores y backtests en el navegador con los mismos datos. |
| `scripts/fetch_data.py` | Descarga precios de Yahoo Finance (`yfinance`) y los guarda en `data/`. |
| `.github/workflows/update-data.yml` | Ejecuta el script cada 15 minutos de lunes a viernes, en horario de mercado, y guarda los cambios. |
| `data/<TICKER>.json` | Velas diarias (2 años, se acumulan) y semanales (10 años). |
| `data/intra/<TICKER>.json` | Velas de 5 minutos por sesión, con premarket. Yahoo entrega 60 días; el repositorio los va acumulando. |
| `data/summary.json` | Último precio y cierres recientes de cada activo, más VIX, tasa a 10 años, Brent y dólar en pesos. |
| `data/USDCLP.json` | Dólar en pesos chilenos, diario (2 años) y semanal (10 años), para medir rentabilidades en pesos. |
| `scripts/strategies.py` | Calcula las estrategias Ichimoku y EMA 9/18 vs SMA 30, el backtest y el estado de cada activo. Al cierre abre un issue con las señales nuevas (GitHub te avisa por correo). |
| `data/signals.json`, `data/strat/` | Estado, backtest y series de cada estrategia. |
| `scripts/ranking.js` → `data/ranking.json` | Prueba unas 100 combinaciones del Laboratorio en todos los activos (diario, 6 a 24 meses) y arma el ranking de la página `#ranking`. Corre una vez al día. |
| `scripts/portfolio.py` → `data/portfolio.json` | Carteras con revisión mensual (rotación por momentum, momentum dual, Faber, filtro de régimen) a 10 años, con todos los activos y solo con índices, más Connors RSI(2) diario en los índices. Página `#carteras`. Corre una vez al día. |
| `scripts/alpaca_paper.py` → `data/alpaca_paper.json` | Replica la estrategia de momentum (top 10, filtro SPY sobre la media de 200) en una cuenta de **simulación** de Alpaca. Corre al cierre y envía órdenes a mercado para la próxima apertura. Apunta fijo al servidor paper: no puede operar dinero real. La página `#paper` (Simulación) muestra el valor de la cuenta frente a SPY y al backtest, las posiciones y las órdenes. |
| `data/planilla.json` | Datos de la planilla original (precios anotados a mano de mayo a octubre de 2026). |

## Puesta en marcha (una sola vez)

1. **Settings → Pages**: en *Source* elige *GitHub Actions*. La acción publica la página después de cada descarga. (Con *Deploy from a branch* también funciona, pero GitHub limita esas publicaciones a unas 10 por hora.)
2. **Actions → Actualizar datos → Run workflow** para la primera descarga.
3. Abre la dirección que muestra Pages (`https://detekuefe.github.io/finanzas-bot/`).

## Simulación con Alpaca (paper trading)

1. Crea una cuenta en [alpaca.markets](https://alpaca.markets) y entra a la cuenta **Paper** (simulación, viene con 100.000 dólares ficticios). Usa una cuenta paper solo para esto: el script vende todo lo que no esté en la cartera de la regla.
2. En la cuenta Paper, genera las claves de API (*API Keys → Generate*).
3. En GitHub, **Settings → Secrets and variables → Actions → New repository secret**: crea `ALPACA_KEY_ID` y `ALPACA_SECRET_KEY` con esas claves.
4. Desde ese día, la corrida de cierre (22:30 UTC) envía las órdenes. Para probar a mano: **Actions → Actualizar datos → Run workflow** después del cierre.

**Botón de emergencia:** *Actions → Alpaca paper: pausar o reanudar → Run workflow* (o los botones de la página `#paper`). `vender_y_pausar` vende todo y deja de operar, `pausar` deja de operar sin vender y `reanudar` (Iniciar bot) quita la pausa y alinea la cuenta con la regla de inmediato.

**Impuestos:** `scripts/alpaca_tax.py` → `data/alpaca_tax.json` calcula cada venta (FIFO) con su ganancia en pesos al dólar observado de cada día y el costo reajustado por IPC (mindicador.cl), más dividendos y retenciones; la página `#paper` estima el Global Complementario según los otros ingresos que ingreses. Es una estimación de apoyo para el contador.

Sin los secrets, el paso solo muestra en el log de la acción las órdenes que enviaría. Para probarlo en tu computador: `python scripts/alpaca_paper.py --dry-run --force`.

## Agregar o quitar activos

Edita la lista `TICKERS` en `scripts/fetch_data.py` y `ALL` en `index.html`.
