# Finanzas bot

Plataforma para seguir los activos de la planilla `Ensayo.xlsx`:
- una página de resumen con el desempeño de los 19 activos,
- una ficha por activo con gráficos intradía (velas de 5 minutos con pivotes PP, R1/S1, R2/S2 y CPR), diarios y semanales (SMA, Bollinger, RSI, MACD).

## Cómo funciona

| Pieza | Qué hace |
|---|---|
| `index.html` | La app. GitHub Pages la publica tal cual. |
| `scripts/fetch_data.py` | Descarga precios de Yahoo Finance (`yfinance`) y los guarda en `data/`. |
| `.github/workflows/update-data.yml` | Ejecuta el script cada 15 minutos de lunes a viernes, en horario de mercado, y guarda los cambios. |
| `data/<TICKER>.json` | Velas diarias (2 años, se acumulan) y semanales (10 años). |
| `data/intra/<TICKER>.json` | Velas de 5 minutos por sesión, con premarket. Yahoo entrega 60 días; el repositorio los va acumulando. |
| `data/summary.json` | Último precio y cierres recientes de cada activo, más VIX, tasa a 10 años y Brent. |
| `data/planilla.json` | Datos de la planilla original (precios anotados a mano de mayo a octubre de 2026). |

## Puesta en marcha (una sola vez)

1. **Settings → Pages**: en *Source* elige *Deploy from a branch*, rama `main`, carpeta `/ (root)`.
2. **Actions → Actualizar datos → Run workflow** para la primera descarga.
3. Abre la dirección que muestra Pages (`https://detekuefe.github.io/finanzas-bot/`).

## Agregar o quitar activos

Edita la lista `TICKERS` en `scripts/fetch_data.py` y `ALL` en `index.html`.
