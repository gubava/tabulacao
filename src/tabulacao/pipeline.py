"""
pipeline.py
------------
Chama data_reader -> column_mapper -> dedup na ordem certa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

from . import data_reader
from .column_mapper import map_columns, ColumnMappingResult
from .dedup import find_duplicates, DedupResult, DuplicateStatus

# Palavras que, no campo Parentesco, indicam que a pessoa é a TITULAR do
# plano (quem contratou, não um dependente dela). Qualquer outro valor
# de parentesco preenchido (Cônjuge, Filho, Filha, Enteado, Pai, Mãe...)
# é tratado como Dependente.
_PARENTESCOS_TITULAR = {
    "titular", "beneficiario titular", "beneficiário titular", "funcionario", "funcionário",
}


def determine_tda(parentesco: Optional[str]) -> Optional[str]:
    """Classifica Titular (T) ou Dependente (D) a partir do texto do
    campo Parentesco — usado como PLANO B quando a base de origem não
    tem uma coluna de Tipo/T-D-A explícita (o caso mais comum: a
    maioria das bases de RH só tem 'Parentesco', nunca um campo
    separado dizendo T ou D)."""
    if not parentesco:
        return None
    texto = parentesco.strip().lower()
    return "T" if texto in _PARENTESCOS_TITULAR else "D"


@dataclass
class ProcessResult:
    df_clean: pd.DataFrame
    column_mapping: ColumnMappingResult
    dedup: DedupResult
    records_found: int = 0
    confirmed_duplicates_pairs: int = 0
    possible_duplicates_pairs: int = 0


def detect_columns(source_paths: List[str]) -> tuple[List[str], ColumnMappingResult]:
    df = data_reader.read_source_file(source_paths[0])
    colunas = list(df.columns)
    mapping = map_columns(colunas)
    return colunas, mapping


def process_sources(source_paths: List[str], manual_overrides: Optional[Dict[str, str]] = None) -> ProcessResult:
    manual_overrides = manual_overrides or {}

    dfs_limpos = []
    mapping_result = None

    for path in source_paths:
        df_bruto = data_reader.read_source_file(path)
        mapping_result = map_columns(list(df_bruto.columns), manual_overrides)

        def col(campo):
            return mapping_result.mapping.get(campo)

        df_limpo = pd.DataFrame()
        df_limpo["_nome"] = df_bruto[col("nome")].map(data_reader.clean_name) if col("nome") else None
        df_limpo["_cpf"] = df_bruto[col("cpf")].map(data_reader.clean_cpf) if col("cpf") else None
        df_limpo["_nascimento"] = df_bruto[col("nascimento")].map(data_reader.parse_date) if col("nascimento") else None
        df_limpo["_sexo"] = df_bruto[col("sexo")].map(data_reader.clean_text) if col("sexo") else None
        df_limpo["_matricula"] = df_bruto[col("matricula")].map(data_reader.clean_text) if col("matricula") else None
        df_limpo["_parentesco"] = df_bruto[col("parentesco")].map(data_reader.clean_text) if col("parentesco") else None
        if col("tda"):
            # a base já tem uma coluna explícita de Tipo/T-D-A — usa ela
            df_limpo["_tda"] = df_bruto[col("tda")].map(data_reader.clean_text)
        else:
            # não tem coluna de Tipo: deduz Titular/Dependente a partir
            # do Parentesco (o cenário mais comum na prática)
            df_limpo["_tda"] = df_limpo["_parentesco"].map(determine_tda)
        df_limpo["_plano"] = df_bruto[col("plano")].map(data_reader.clean_text) if col("plano") else None
        df_limpo["_mensalidade"] = df_bruto[col("mensalidade")].map(data_reader.clean_money) if col("mensalidade") else None

        dfs_limpos.append(df_limpo)

    df_final = pd.concat(dfs_limpos, ignore_index=True)
    dedup_result = find_duplicates(df_final)

    return ProcessResult(
        df_clean=df_final,
        column_mapping=mapping_result,
        dedup=dedup_result,
        records_found=len(df_final),
        confirmed_duplicates_pairs=sum(1 for p in dedup_result.pairs if p.status == DuplicateStatus.CONFIRMED),
        possible_duplicates_pairs=sum(1 for p in dedup_result.pairs if p.status == DuplicateStatus.POSSIBLE),
    )


def resolve_confirmed_duplicates(result: ProcessResult) -> pd.DataFrame:
    df = result.df_clean
    indices_para_remover = set()
    for par in result.dedup.pairs:
        if par.status == DuplicateStatus.CONFIRMED:
            indices_para_remover.add(par.index_b)
    return df.drop(index=list(indices_para_remover)).reset_index(drop=True)


def apply_user_decisions(df: pd.DataFrame, decisions: Dict[str, str]) -> pd.DataFrame:
    indices_para_remover = set()
    for chave, decisao in decisions.items():
        idx_a_str, idx_b_str = chave.split("-")
        idx_a, idx_b = int(idx_a_str), int(idx_b_str)
        if decisao == "excluir":
            indices_para_remover.add(idx_a)
            indices_para_remover.add(idx_b)
        elif decisao == "manter_1":
            indices_para_remover.add(idx_b)
        elif decisao == "manter_2":
            indices_para_remover.add(idx_a)
    indices_validos = [i for i in indices_para_remover if i in df.index]
    return df.drop(index=indices_validos).reset_index(drop=True)


def _texto_ou_vazio(valor) -> str:
    """Lê um valor vindo de uma célula do pandas e devolve texto limpo,
    ou '' se estiver vazio.

    IMPORTANTE: 'valor or \"\"' sozinho NÃO é suficiente aqui — quando
    uma célula de CSV está genuinamente vazia, o pandas às vezes guarda
    isso como NaN (um 'float' especial), não como None nem como texto
    vazio. E 'NaN or \"\"' em Python devolve o próprio NaN de volta (NaN
    é um valor "verdadeiro" pro Python, por estranho que pareça) — por
    isso essa checagem usa pd.isna() também, não só 'or'."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor)


def _numero_ou_none(valor):
    """Mesma ideia de _texto_ou_vazio, mas para campos numéricos (ex.:
    Mensalidade) — um valor ausente vindo do pandas também pode chegar
    aqui como NaN em vez de None."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    return valor


def build_output_records(df: pd.DataFrame) -> List[dict]:
    registros = []
    for _, row in df.iterrows():
        registros.append({
            "nome": _texto_ou_vazio(row.get("_nome")),
            "cpf": _texto_ou_vazio(row.get("_cpf")),
            "nascimento": row.get("_nascimento"),
            "sexo": _texto_ou_vazio(row.get("_sexo")),
            "matricula": _texto_ou_vazio(row.get("_matricula")),
            "parentesco": _texto_ou_vazio(row.get("_parentesco")),
            "tda": _texto_ou_vazio(row.get("_tda")),
            "plano": _texto_ou_vazio(row.get("_plano")),
            "mensalidade": _numero_ou_none(row.get("_mensalidade")),
        })
    return registros
