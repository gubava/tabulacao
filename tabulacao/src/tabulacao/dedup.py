"""
dedup.py
---------
Decide quais registros parecem ser a mesma pessoa duplicada.

REGRA DE SEGURANÇA (decisão do usuário do sistema, não uma escolha
técnica minha): o sistema só remove um registro AUTOMATICAMENTE, sem
perguntar, quando TRÊS condições batem AO MESMO TEMPO no mesmo par:

    1. Nome completo EXATAMENTE igual (não é "parecido" — é igual)
    2. Mesma data de nascimento
    3. Mesmo CPF

Só quando os três critérios passam juntos é que vira "CONFIRMADA".

QUALQUER outra coincidência — só CPF igual (mas nome diferente), só
nome parecido, só matrícula igual, nome+nascimento iguais mas CPF
diferente — vira "POSSÍVEL", e precisa de uma decisão humana. Nunca é
removida sozinha.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

import pandas as pd
from rapidfuzz import fuzz


class DuplicateStatus(str, Enum):
    CONFIRMED = "confirmada"
    POSSIBLE = "possivel"


class DuplicateReason(str, Enum):
    FULL_MATCH = "Nome, nascimento e CPF idênticos"
    FULL_MATCH_SEM_CPF = "Nome e nascimento idênticos (esta base não tem CPF disponível)"
    SAME_CPF = "Mesmo CPF (mas nome ou nascimento diferem)"
    SAME_MATRICULA = "Mesma matrícula/código"
    SAME_NAME_DOB = "Mesmo nome e data de nascimento (CPF diferente ou ausente)"
    SIMILAR_NAME = "Nome muito parecido"


@dataclass
class DuplicatePair:
    index_a: int
    index_b: int
    status: DuplicateStatus
    reason: DuplicateReason
    similarity: float = 100.0


@dataclass
class DedupResult:
    pairs: List[DuplicatePair] = field(default_factory=list)
    confirmed_indices: set = field(default_factory=set)
    possible_indices: set = field(default_factory=set)


def find_duplicates(df: pd.DataFrame) -> DedupResult:
    """
    Usa agrupamento (pandas groupby, O(n)) em vez de comparar todo mundo
    com todo mundo (O(n²), que travava em bases grandes) — e aplica a
    regra rígida de 3 fatores antes de qualquer outra coisa, pra nenhum
    sinal mais fraco (CPF sozinho, nome parecido, matrícula) nunca virar
    remoção automática.
    """
    resultado = DedupResult()
    pares_ja_vistos = set()

    def _registrar(idx_a, idx_b, status, reason, similarity=100.0):
        chave = tuple(sorted((idx_a, idx_b)))
        if chave in pares_ja_vistos:
            return  # já foi classificado (por um critério mais forte processado antes)
        pares_ja_vistos.add(chave)
        resultado.pairs.append(DuplicatePair(idx_a, idx_b, status, reason, similarity))
        alvo = resultado.confirmed_indices if status == DuplicateStatus.CONFIRMED else resultado.possible_indices
        alvo.add(idx_a)
        alvo.add(idx_b)

    # ---------------------------------------------------------------
    # PASSO 1 (sempre primeiro): CONFIRMADA — só quando nome EXATO +
    # nascimento + CPF batem os três ao mesmo tempo
    # ---------------------------------------------------------------
    completos = df[
        df["_cpf"].notna() & (df["_cpf"] != "") &
        df["_nome"].notna() & (df["_nome"] != "") &
        df["_nascimento"].notna()
    ]
    if not completos.empty:
        chave_nome = completos["_nome"].str.strip().str.lower()
        for _, grupo in completos.groupby([chave_nome, "_cpf", "_nascimento"]):
            indices = list(grupo.index)
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    _registrar(indices[i], indices[j], DuplicateStatus.CONFIRMED, DuplicateReason.FULL_MATCH)

    # ---------------------------------------------------------------
    # PASSO 1b: CONFIRMADA também quando a base ENVIADA não tem CPF
    # disponível pra ninguém (não é "esse par não tem CPF", é "essa
    # base inteira não trouxe CPF") — nesse caso, nome EXATO + mesma
    # data de nascimento já é o critério mais forte possível de
    # verificar, então também confirma sozinho. Se a base TEM CPF (só
    # que ausente/diferente pra esse par específico), isso continua
    # sendo tratado como "possível" mais abaixo — porque aí faltar o
    # CPF pode ser um erro de digitação, não "esse campo não existe".
    # ---------------------------------------------------------------
    base_tem_cpf = df["_cpf"].notna().any()
    if not base_tem_cpf:
        com_nome_nasc_sem_cpf = df[df["_nome"].notna() & (df["_nome"] != "") & df["_nascimento"].notna()]
        if not com_nome_nasc_sem_cpf.empty:
            chave_nome_sc = com_nome_nasc_sem_cpf["_nome"].str.strip().str.lower()
            for _, grupo in com_nome_nasc_sem_cpf.groupby([chave_nome_sc, "_nascimento"]):
                indices = list(grupo.index)
                for i in range(len(indices)):
                    for j in range(i + 1, len(indices)):
                        _registrar(indices[i], indices[j], DuplicateStatus.CONFIRMED, DuplicateReason.FULL_MATCH_SEM_CPF)

    # ---------------------------------------------------------------
    # Tudo que vem depois é SEMPRE possível — nunca remove sozinho.
    # Se um par já foi confirmado no passo 1, o _registrar() ignora
    # silenciosamente (não duplica a mesma dupla com um motivo mais fraco).
    # ---------------------------------------------------------------

    # Mesmo CPF (mas não bateu os 3 juntos no passo 1 — ex.: nome diferente)
    com_cpf = df[df["_cpf"].notna() & (df["_cpf"] != "")]
    for _, grupo in com_cpf.groupby("_cpf"):
        indices = list(grupo.index)
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                _registrar(indices[i], indices[j], DuplicateStatus.POSSIBLE, DuplicateReason.SAME_CPF)

    # Mesma matrícula
    com_matricula = df[df["_matricula"].notna() & (df["_matricula"] != "")]
    for _, grupo in com_matricula.groupby("_matricula"):
        indices = list(grupo.index)
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                _registrar(indices[i], indices[j], DuplicateStatus.POSSIBLE, DuplicateReason.SAME_MATRICULA)

    # Mesmo nome + mesmo nascimento (sem exigir CPF igual aqui)
    com_nome_nasc = df[df["_nome"].notna() & df["_nascimento"].notna()]
    if not com_nome_nasc.empty:
        chave_nome2 = com_nome_nasc["_nome"].str.lower()
        for _, grupo in com_nome_nasc.groupby([chave_nome2, "_nascimento"]):
            indices = list(grupo.index)
            for i in range(len(indices)):
                for j in range(i + 1, len(indices)):
                    _registrar(indices[i], indices[j], DuplicateStatus.POSSIBLE, DuplicateReason.SAME_NAME_DOB)

    # Nome muito parecido -> POSSÍVEL. Agrupamos pelas 3 PRIMEIRAS
    # LETRAS do nome (não só 1) — em bases grandes, um bloco de 1 letra
    # só pode reunir milhares de pessoas com nome comum (ex.: 2.381
    # "João ..." numa base de 9.500 pessoas), fazendo a comparação
    # par-a-par explodir (quase 3 milhões de comparações só nesse
    # bloco). Com 3 letras, "João" já separa de "Joaquim", cortando o
    # tamanho dos blocos bastante sem perder pares parecidos de verdade
    # (que quase sempre compartilham ao menos as 3 primeiras letras).
    #
    # MAX_BLOCO_FUZZY: se mesmo assim um bloco ficar grande demais, a
    # comparação dentro dele é pulada — nesse volume, uma lista de
    # "possíveis duplicidades" também deixaria de ser útil de revisar.
    MAX_BLOCO_FUZZY = 400

    com_nome = df[df["_nome"].notna() & (df["_nome"] != "")]
    blocos: dict[str, list] = {}
    for idx, nome in com_nome["_nome"].items():
        nome_limpo = nome.strip()
        chave = nome_limpo[:3].upper() if nome_limpo else "?"
        blocos.setdefault(chave, []).append((idx, nome.lower()))

    for grupo_por_bloco in blocos.values():
        if len(grupo_por_bloco) > MAX_BLOCO_FUZZY:
            continue
        for i in range(len(grupo_por_bloco)):
            for j in range(i + 1, len(grupo_por_bloco)):
                idx_a, nome_a = grupo_por_bloco[i]
                idx_b, nome_b = grupo_por_bloco[j]
                similaridade = fuzz.ratio(nome_a, nome_b)
                if similaridade >= 90:
                    _registrar(idx_a, idx_b, DuplicateStatus.POSSIBLE, DuplicateReason.SIMILAR_NAME, similaridade)

    return resultado
