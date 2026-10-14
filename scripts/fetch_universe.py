"""Descarga 3 años de cierres diarios ajustados (incluyen dividendos) de un universo amplio de acciones:
los miembros del Nasdaq-100 y las mayores empresas del S&P 500, más SPY y QQQ como referencias.

La lista es la composición actual de los índices: las empresas que salieron en el camino no están
(sesgo de supervivencia), lo que favorece un poco a cualquier backtest sobre este universo.
Escribe data/universe.json. Corre una vez al día desde la acción "Actualizar datos".
"""
import json
import os
import sys

import yfinance as yf

NASDAQ100 = """AAPL MSFT NVDA AMZN GOOGL META AVGO TSLA COST NFLX TMUS ASML CSCO AMD PEP LIN ADBE AZN INTU TXN
QCOM ISRG BKNG AMGN AMAT PDD HON CMCSA ARM ADP MU PANW GILD LRCX ADI VRTX SBUX MELI KLAC INTC CRWD APP MSTR
PLTR CEG MDLZ CTAS ABNB REGN SNPS CDNS FTNT MAR ORLY DASH WDAY CSX ADSK PYPL MRVL ROP NXPI CHTR AEP PCAR
TTWO MNST FAST PAYX CPRT KDP ROST AXON EXC VRSK FANG CTSH BKR XEL DDOG EA IDXX ODFL TEAM KHC CCEP LULU ZS
GEHC CSGP ON DXCM TTD BIIB CDW GFS WBD MCHP SHOP TRI""".split()
SP500 = """BRK-B JPM V LLY UNH XOM MA JNJ PG HD WMT ABBV BAC KO CRM ORCL CVX MRK WFC ACN MCD IBM GE ABT PM DIS
CAT GS NOW AXP MS RTX T VZ SPGI UBER BLK NEE PFE LOW TMO DHR SCHW BA DE UNP C ETN BSX KKR SYK ANET COP
MMC PGR TJX BX GEV VST DELL SNDK WDC STX MU NTAP""".split()
REFS = ["SPY", "QQQ"]
DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def main():
    tickers = list(dict.fromkeys(REFS + NASDAQ100 + SP500))
    df = yf.download(tickers, period="3y", interval="1d", auto_adjust=True, progress=False, threads=True)
    close = df["Close"].dropna(how="all")
    dates = [d.strftime("%Y-%m-%d") for d in close.index]
    out = {"dates": dates, "nasdaq100": [], "sp500": [], "closes": {}}
    for t in tickers:
        if t not in close.columns:
            continue
        s = close[t]
        if s.notna().sum() < 60:
            continue
        out["closes"][t] = [None if v != v else round(float(v), 3) for v in s.tolist()]
        if t in NASDAQ100:
            out["nasdaq100"].append(t)
        if t in SP500:
            out["sp500"].append(t)
    if len(out["closes"]) < len(tickers) * 0.8:
        sys.exit(f"Solo llegaron {len(out['closes'])} de {len(tickers)} activos; no se sobrescribe el archivo")
    with open(os.path.join(DATA, "universe.json"), "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"Universo: {len(out['closes'])} activos, {len(dates)} días")


if __name__ == "__main__":
    main()
