"""
data_reader.py
----------------
Camada de LEITURA. Só sabe fazer uma coisa: pegar um valor "sujo" (de
uma célula de planilha) e devolver um valor "limpo" e confiável.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

import pandas as pd


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def clean_text(value) -> Optional[str]:
    if is_blank(value):
        return None
    return " ".join(str(value).split())


def clean_name(value) -> Optional[str]:
    texto = clean_text(value)
    if texto is None:
        return None
    return texto.title()


def clean_cpf(value) -> Optional[str]:
    if is_blank(value):
        return None
    numeros = re.sub(r"\D", "", str(value))
    return numeros if len(numeros) == 11 else None


def clean_money(value) -> Optional[float]:
    if is_blank(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    texto = str(value).strip()
    texto = re.sub(r"[R$\s]", "", texto)
    texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


_DATE_FORMATS = [
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y/%m/%d",
    "%d/%m/%y", "%d.%m.%Y",
]


def parse_date(value) -> Optional[date]:
    """Reconhece data em vários formatos BR, incluindo com horário
    grudado ('1990-01-15 00:00:00') e número de série do Excel com
    fração de horário (45658.5)."""
    if value is None or is_blank(value):
        return None
    if isinstance(value, (datetime, date)):
        return value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
    if isinstance(value, pd.Timestamp):
        return value.date()

    text = str(value).strip()

    if re.fullmatch(r"\d{4,6}(\.\d+)?", text):
        try:
            serial = float(text)
            base = datetime(1899, 12, 30)
            return (base + pd.Timedelta(days=serial)).date()
        except Exception:  # noqa: BLE001
            pass

    texto_sem_hora = re.split(r"[T ]\d{1,2}:\d{2}", text)[0].strip()
    candidatos = [texto_sem_hora, text] if texto_sem_hora != text else [text]

    for candidato in candidatos:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidato, fmt).date()
            except ValueError:
                continue
    return None


def read_source_file(path) -> pd.DataFrame:
    path = str(path)
    if path.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "latin1", "cp1252"):
            for sep in (";", ","):
                try:
                    df = pd.read_csv(path, dtype=str, encoding=encoding, sep=sep)
                    if df.shape[1] > 1:
                        return df
                except Exception:  # noqa: BLE001
                    continue
        raise ValueError(f"Não foi possível ler o arquivo CSV: {path}")
    return pd.read_excel(path, dtype=str)
