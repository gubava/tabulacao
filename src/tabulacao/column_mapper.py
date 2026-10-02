"""
column_mapper.py
------------------
Descobre sozinho qual coluna da planilha é "nome", "CPF", "nascimento"
etc. — comparando o cabeçalho de cada coluna com uma lista de sinônimos
conhecidos.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List

CANONICAL_FIELDS: Dict[str, List[str]] = {
    "nome": ["nome", "beneficiario", "beneficiário", "segurado", "colaborador", "funcionario"],
    "cpf": ["cpf", "c.p.f.", "documento"],
    "nascimento": ["nascimento", "data nascimento", "dt nascimento", "data de nascimento"],
    "sexo": ["sexo", "genero", "gênero"],
    "matricula": ["matricula", "matrícula", "codigo", "código", "credencial"],
    "parentesco": ["parentesco", "vinculo", "vínculo", "grau"],
    "tda": ["tipo", "t/d/a", "tda"],
    "plano": ["plano", "produto"],
    "mensalidade": ["mensalidade", "valor", "valor plano"],
}


def _normalizar(texto: str) -> str:
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c))


@dataclass
class ColumnMappingResult:
    mapping: Dict[str, str] = field(default_factory=dict)
    unmatched_fields: List[str] = field(default_factory=list)


def map_columns(colunas_disponiveis: List[str], manual_overrides: Dict[str, str] | None = None) -> ColumnMappingResult:
    manual_overrides = manual_overrides or {}
    colunas_normalizadas = {_normalizar(c): c for c in colunas_disponiveis}

    resultado = ColumnMappingResult()

    for campo, sinonimos in CANONICAL_FIELDS.items():
        if campo in manual_overrides and manual_overrides[campo]:
            resultado.mapping[campo] = manual_overrides[campo]
            continue

        encontrado = None
        for sinonimo in sinonimos:
            candidato = colunas_normalizadas.get(_normalizar(sinonimo))
            if candidato:
                encontrado = candidato
                break

        if encontrado:
            resultado.mapping[campo] = encontrado
        else:
            resultado.unmatched_fields.append(campo)

    return resultado
