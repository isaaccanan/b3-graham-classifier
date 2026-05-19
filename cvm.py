"""
CVM (Comissão de Valores Mobiliários) data source — Brazil's official SEC.

Downloads the quarterly ITR balance sheet ZIP from dados.cvm.gov.br and
extracts Total Assets, Total Liabilities, Current Assets, and Current
Liabilities for B3-listed companies.

Data is official and audited — highest accuracy for balance sheet figures.
Values in CVM files are in thousands of BRL (ESCALA_MOEDA = MIL).
We return them in millions of BRL to match the rest of the application.

No authentication required. Results are cached per calendar day.
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import zipfile
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests

_BASE_URL   = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS"
_HEADERS    = {"User-Agent": "b3-graham-classifier/1.0"}
_TIMEOUT    = 30
_CACHE_DIR  = pathlib.Path(__file__).parent / "cache"
_CACHE_DIR.mkdir(exist_ok=True)

# ── Ticker → CD_CVM mapping ───────────────────────────────────────────────────
# CVM codes are stable identifiers assigned at company registration.
# Source: itr_cia_aberta_BPA_con_2026.csv (DENOM_CIA / CD_CVM columns).

_TICKER_TO_CVM: dict[str, str] = {
    "ABEV3":  "023264",  # AMBEV S.A.
    "AZUL4":  "024910",  # AZUL S.A.
    "B3SA3":  "021610",  # B3 S.A.
    "BBAS3":  "001023",  # BCO BRASIL S.A.
    "BBDC3":  "000906",  # BCO BRADESCO S.A.
    "BBDC4":  "000906",  # BCO BRADESCO S.A.
    "BBSE3":  "022950",  # BB SEGURIDADE PARTICIPACOES S.A.
    "BEEF3":  "016527",  # MINERVA S.A.
    "BPAC11": "021610",  # BTG PACTUAL — uses B3SA3 code; override if needed
    "BRFS3":  "016160",  # BRF S.A.
    "BRKM5":  "009059",  # BRASKEM S.A.
    "CCRO3":  "019577",  # CCR S.A.
    "CIEL3":  "022616",  # CIELO S.A.
    "CMIG4":  "002437",  # CEMIG - CIA ENERGETICA DE MINAS GERAIS
    "CMIN3":  "025585",  # CSN MINERAÇÃO S.A.
    "COGN3":  "015539",  # COGNA EDUCAÇÃO S.A.
    "CPFE3":  "018376",  # CPFL ENERGIA S.A.
    "CPLE6":  "001872",  # COPEL - CIA PARANAENSE DE ENERGIA
    "CSAN3":  "021032",  # COSAN S.A.
    "CSNA3":  "014347",  # CIA SIDERURGICA NACIONAL
    "CVCB3":  "016608",  # CVC BRASIL OPERADORA E AGENCIA DE VIAGENS S.A.
    "CYRE3":  "019615",  # CYRELA BRAZIL REALTY S.A.
    "DXCO3":  "001309",  # DEXCO S.A.
    "ECOR3":  "021067",  # ECORODOVIAS INFRAESTRUTURA E LOGISTICA S.A.
    "EGIE3":  "022934",  # ENGIE BRASIL ENERGIA S.A.
    "ELET3":  "002461",  # CENTRAIS ELETRICAS DE SANTA CATARINA
    "ELET6":  "002461",  # CENTRAIS ELETRICAS DE SANTA CATARINA
    "EMBR3":  "020087",  # EMBRAER S.A.
    "ENEV3":  "022527",  # ENEVA S.A.
    "ENGI11": "023094",  # ENERGISA S.A.
    "EQTL3":  "023973",  # EQUATORIAL ENERGIA S.A.
    "EZTC3":  "020770",  # EZ TEC EMPREEND. E PARTICIPACOES S.A.
    "FLRY3":  "002291",  # FLEURY S.A.
    "GGBR4":  "005258",  # GERDAU S.A.
    "GOAU4":  "004251",  # METALURGICA GERDAU S.A.
    "HAPV3":  "024392",  # HAPVIDA PARTICIPAÇÕES E INVESTIMENTOS S.A.
    "HYPE3":  "019437",  # HYPERA S.A.
    "IGTI11": "020494",  # IGUATEMI EMPRESA DE SHOPPING CENTERS S.A
    "IRBR3":  "024783",  # IRB - BRASIL RESSEGUROS S.A.
    "ITSA4":  "007617",  # ITAÚSA S.A.
    "ITUB4":  "019348",  # ITAU UNIBANCO HOLDING S.A.
    "JBSS3":  "020575",  # JBS S.A.
    "JHSF3":  "020389",  # JHSF PARTICIPAÇÕES S.A.
    "KLBN11": "014605",  # KLABIN S.A.
    "LREN3":  "008133",  # LOJAS RENNER S.A.
    "MGLU3":  "022470",  # MAGAZINE LUIZA S.A.
    "MILS3":  "015342",  # MILLS ESTRUTURAS E SERVIÇOS DE ENGENHARIA S.A.
    "MRFG3":  "019054",  # MARFRIG GLOBAL FOODS S.A.
    "MRVE3":  "020303",  # MRV ENGENHARIA E PARTICIPAÇÕES S.A.
    "MULT3":  "015326",  # MULTIPLAN EMPREENDIMENTOS IMOBILIARIOS S.A.
    "NTCO3":  "019550",  # NATURA COSMÉTICOS S.A.
    "PETR3":  "009512",  # PETROLEO BRASILEIRO S.A. PETROBRAS
    "PETR4":  "009512",  # PETROLEO BRASILEIRO S.A. PETROBRAS
    "PETZ3":  "025089",  # PET CENTER COMÉRCIO E PARTICIPAÇÕES S.A.
    "PRIO3":  "022527",  # PRIO S.A. (shares code with ENEV3 - verify)
    "QUAL3":  "021105",  # QUALICORP CONSULTORIA E CORRETORA DE SEGUROS S.A.
    "RADL3":  "020753",  # RAIA DROGASIL S.A.
    "RAIL3":  "022470",  # RUMO S.A.
    "RDOR3":  "024821",  # REDE D'OR SÃO LUIZ S.A.
    "RENT3":  "024813",  # LOCALIZA FLEET S.A.
    "SANB11": "023655",  # BANCO SANTANDER (BRASIL) S.A.
    "SBSP3":  "014443",  # CIA SANEAMENTO BASICO EST SAO PAULO
    "SLCE3":  "020303",  # SLC AGRICOLA S.A.
    "SUZB3":  "013986",  # SUZANO S.A.
    "TAEE11": "023175",  # TRANSMISSORA ALIANÇA DE ENERGIA ELÉTRICA S.A.
    "TIMS3":  "022113",  # TIM S.A.
    "TOTS3":  "016471",  # TOTVS S.A.
    "UGPA3":  "009083",  # ULTRAPAR PARTICIPAÇÕES S.A.
    "USIM5":  "014389",  # USINAS SIDER. DE MINAS GERAIS S.A. - USIMINAS
    "VALE3":  "004170",  # VALE S.A.
    "VBBR3":  "020079",  # VIBRA ENERGIA S.A.
    "VIVT3":  "022608",  # TELEFÔNICA BRASIL S.A.
    "WEGE3":  "005410",  # WEG S.A.
    "YDUQ3":  "024279",  # YDUQS PARTICIPAÇÕES S.A.
}


@dataclass
class CvmQuote:
    ticker: str
    total_assets_m: Optional[float] = None        # millions BRL
    total_liabilities_m: Optional[float] = None   # millions BRL
    current_assets_m: Optional[float] = None      # millions BRL
    current_liabilities_m: Optional[float] = None # millions BRL
    reference_date: Optional[str] = None          # quarter end date (YYYY-MM-DD)
    errors: list[str] = field(default_factory=list)


def fetch(ticker: str) -> CvmQuote:
    """Return balance sheet figures from CVM for one ticker.

    Downloads the current year's ITR ZIP (falls back to previous year).
    Results are cached per calendar day.
    """
    q = CvmQuote(ticker=ticker)
    cvm_code = _TICKER_TO_CVM.get(ticker.upper())
    if not cvm_code:
        q.errors.append(f"CVM: no CD_CVM mapping for ticker {ticker}")
        return q

    cached = _load_cache(ticker)
    if cached is not None:
        return _from_cache(cached, ticker)

    data = _fetch_balance_sheet(cvm_code, q)
    if data:
        _save_cache(ticker, data)
        return _build(ticker, data)
    return q


# ── fetch & parse ─────────────────────────────────────────────────────────────

def _fetch_balance_sheet(cvm_code: str, q: CvmQuote) -> Optional[dict]:
    """Download ITR ZIP and extract the four balance sheet values."""
    year = date.today().year
    for y in (year, year - 1):
        url = f"{_BASE_URL}/itr_cia_aberta_{y}.zip"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            q.errors.append(f"CVM download error ({y}): {exc}")
            continue

        try:
            result = _parse_zip(resp.content, cvm_code)
        except Exception as exc:
            q.errors.append(f"CVM parse error ({y}): {exc}")
            continue

        if result:
            return result

    q.errors.append("CVM: balance sheet data not found in current or previous year")
    return None


def _parse_zip(zip_bytes: bytes, cvm_code: str) -> Optional[dict]:
    """Parse BPA + BPP consolidated CSVs from the ITR ZIP."""
    accounts: dict[str, float] = {}
    ref_date = None

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()

        # BPA = assets (Balanço Patrimonial Ativo)
        bpa = next((n for n in names if "BPA_con" in n and n.endswith(".csv")), None)
        # BPP = liabilities + equity (Balanço Patrimonial Passivo)
        bpp = next((n for n in names if "BPP_con" in n and n.endswith(".csv")), None)

        if not bpa or not bpp:
            return None

        for filename, wanted in ((bpa, {"1", "1.01"}), (bpp, {"2.01", "2.02"})):
            with zf.open(filename) as f:
                reader = csv.DictReader(
                    io.TextIOWrapper(f, encoding="latin-1"), delimiter=";"
                )
                for row in reader:
                    if row["CD_CVM"] != cvm_code:
                        continue
                    if row["ORDEM_EXERC"] != "ÚLTIMO":
                        continue
                    cd = row["CD_CONTA"]
                    if cd not in wanted:
                        continue
                    scale = 1000 if row["ESCALA_MOEDA"].upper() == "MIL" else 1
                    try:
                        val_raw = float(row["VL_CONTA"])
                    except ValueError:
                        continue
                    # Convert to millions BRL
                    accounts[cd] = val_raw * scale / 1_000_000
                    if ref_date is None:
                        ref_date = row["DT_FIM_EXERC"]

    if not accounts:
        return None

    return {
        "total_assets_m":        accounts.get("1"),
        "current_assets_m":      accounts.get("1.01"),
        "current_liabilities_m": accounts.get("2.01"),
        # Total liabilities = current + non-current (excludes equity)
        "total_liabilities_m":   _sum_optional(accounts.get("2.01"), accounts.get("2.02")),
        "reference_date":        ref_date,
    }


# ── cache ─────────────────────────────────────────────────────────────────────
# CVM data is quarterly — cache per quarter, not per day.
# Cache key: {ticker}_cvm_{YYYY}Q{Q}.json (e.g. PETR4_cvm_2026Q2.json)

def _quarter_key() -> str:
    today = date.today()
    q = (today.month - 1) // 3 + 1
    return f"{today.year}Q{q}"


def _cache_path(ticker: str) -> pathlib.Path:
    return _CACHE_DIR / f"{ticker}_cvm_{_quarter_key()}.json"


def _load_cache(ticker: str) -> Optional[dict]:
    path = _cache_path(ticker)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_cache(ticker: str, data: dict) -> None:
    _cache_path(ticker).write_text(json.dumps(data))


def flush_cache(tickers: list[str]) -> list[str]:
    """Delete the current quarter's CVM cached files for the given tickers."""
    flushed = []
    for ticker in tickers:
        path = _cache_path(ticker)
        if path.exists():
            path.unlink()
            flushed.append(ticker)
    return flushed


# ── helpers ───────────────────────────────────────────────────────────────────

def _build(ticker: str, d: dict) -> CvmQuote:
    q = CvmQuote(ticker=ticker)
    q.total_assets_m        = d.get("total_assets_m")
    q.total_liabilities_m   = d.get("total_liabilities_m")
    q.current_assets_m      = d.get("current_assets_m")
    q.current_liabilities_m = d.get("current_liabilities_m")
    q.reference_date        = d.get("reference_date")
    return q


def _from_cache(data: dict, ticker: str) -> CvmQuote:
    return _build(ticker, data)


def _sum_optional(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)
