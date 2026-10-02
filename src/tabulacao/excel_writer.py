"""
excel_writer.py
-----------------
Preenche o modelo REAL "Modelo_de_Estudo.xlsx" com os registros já
tratados, preservando as fórmulas que o modelo já tinha (Idade e Faixa
2 são calculadas automaticamente pelo próprio Excel, a partir da data
de Nascimento — nunca escrevemos um valor fixo nessas duas colunas).

TRÊS DESCOBERTAS IMPORTANTES feitas testando contra o arquivo real:

1. `ws.cell(row=r, column=c, value=None)` NÃO limpa a célula no
   openpyxl — ele trata 'value=None' como 'nenhum valor foi informado',
   deixando o que já estava lá (dado de exemplo do modelo). Para
   escrever/limpar um valor que pode ser None de verdade, é preciso
   usar `ws.cell(row=r, column=c).value = X` — padrão usado aqui.

2. A linha 2 do modelo tem a Idade como um VALOR FIXO (não fórmula) —
   as linhas "molde" mais pra baixo (ex.: linha 123, sem dado, só
   fórmula pronta) mostram o padrão de verdade: Idade também é fórmula,
   calculada a partir do Nascimento. Por isso usamos a linha 123 (não a
   2) como referência das fórmulas de Idade/Faixa.

3. A coluna Sexo usa uma fórmula com referência a um arquivo EXTERNO
   (um dicionário nome->sexo que não viaja com este arquivo). O Excel
   guarda uma CÓPIA EM CACHE desses dados dentro do próprio arquivo,
   mas o LibreOffice não usa esse cache ao recalcular (mostra #NOME?) —
   não dá pra garantir que toda ferramenta que abrir o arquivo saiba
   resolver isso. Por segurança, em vez de copiar essa fórmula, LEMOS
   a mesma tabela de cache embutida no arquivo e calculamos o Sexo
   diretamente em Python, escrevendo o resultado como texto — funciona
   em qualquer programa, sem depender de nenhum link externo.

A área real de dados da aba termina na linha 250 — depois disso tem um
pequeno resumo (contagem de cônjuges/filhos) que nunca deve ser tocado.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import openpyxl

SHEET_NAME = "Base de Vidas"

COL_TDA = 1
COL_NOME = 2
COL_SEXO = 3
COL_NASCIMENTO = 4
COL_IDADE = 5          # FÓRMULA — nunca escrita diretamente
COL_FAIXA = 6          # FÓRMULA — nunca escrita diretamente
COL_PLANO = 7
COL_VALOR = 8
COL_PARENTESCO = 9
COL_CIDADE = 10
COL_UF = 11
COL_SITUACAO = 12
COL_CID = 13
COL_EMPRESA = 14

FIRST_DATA_ROW = 2
FORMULA_TEMPLATE_ROW = 123
# Suporta até 10.000 vidas (linha 2 até 10001). As fórmulas de
# Idade/Faixa são geradas dinamicamente pra qualquer linha dentro desse
# intervalo (não dependem de já existir uma fórmula pronta naquela
# linha do modelo) — então aumentar esse número não exige nenhuma outra
# mudança no arquivo .xlsx em si.
#
# O modelo original tinha só ~250 linhas de formato pronto, seguidas de
# duas células de texto solto ("23 Conjuge"/"23 Filhos", em B257/B258)
# — confirmei que isso NÃO é uma fórmula nem é referenciado em nenhum
# outro lugar da planilha, só uma anotação manual que sobrou de um
# cliente anterior. Por isso é seguro tratar essas células como
# qualquer outro dado de exemplo a limpar, sem risco de quebrar nada.
MAX_TEMPLATE_ROW = 10001

_ROW_REF_RE = re.compile(r"([A-Z]{1,3})" + str(FORMULA_TEMPLATE_ROW) + r"\b")


def _formula_para_linha(formula_modelo: str, linha: int) -> str:
    if linha == FORMULA_TEMPLATE_ROW:
        return formula_modelo
    return _ROW_REF_RE.sub(lambda m: f"{m.group(1)}{linha}", formula_modelo)


def _set(ws, row: int, col: int, value) -> None:
    ws.cell(row=row, column=col).value = value


def _carregar_tabela_sexo(wb) -> Dict[str, str]:
    """Lê a tabela nome->sexo que já vem em cache dentro do próprio
    arquivo (ver descoberta 3 acima). Se por algum motivo o arquivo não
    tiver esse cache, devolve um dicionário vazio (o Sexo simplesmente
    fica em branco para todo mundo, em vez de travar o processo)."""
    tabela: Dict[str, str] = {}
    try:
        link = wb._external_links[0]
        sheet_data = link.externalBook.sheetDataSet.sheetData[0]
        for row in sheet_data.row:
            nome_val, sexo_val = None, None
            for cell in row.cell:
                col_letter = "".join(ch for ch in cell.r if ch.isalpha())
                if col_letter == "A":
                    nome_val = cell.v
                elif col_letter == "B":
                    sexo_val = cell.v
            if nome_val and sexo_val:
                tabela[str(nome_val).strip().upper()] = str(sexo_val).strip().upper()
    except (IndexError, AttributeError):
        pass
    return tabela


def _normalizar_sexo_da_base(valor) -> Optional[str]:
    """Se a base de origem já tem uma coluna de Sexo preenchida (ex.:
    'Masculino', 'Feminino', 'M', 'F', 'masc'...), usa esse valor real
    em vez de adivinhar pelo nome — é sempre mais confiável que uma
    estimativa, quando disponível.

    'valor' pode chegar aqui como vários tipos diferentes, não só texto
    — uma célula vazia de CSV às vezes vira um 'NaN' (um tipo float
    especial do pandas) em vez de string vazia ou None — por isso a
    checagem aceita qualquer tipo e só usa como texto de verdade."""
    if valor is None:
        return None
    if isinstance(valor, float):
        return None  # célula vazia/NaN — não tem sexo informado
    texto = str(valor).strip().upper()
    if not texto:
        return None
    if texto.startswith("M"):
        return "M"
    if texto.startswith("F"):
        return "F"
    return None


def _calcular_sexo_por_nome(nome: str, tabela_sexo: Dict[str, str]) -> Optional[str]:
    """PLANO B: quando a base não trouxe Sexo pra essa pessoa, estima a
    partir do primeiro nome, usando a mesma lógica da fórmula original
    do modelo (ex.: 'Carlos Eduardo Souza' -> procura só 'CARLOS')."""
    if not nome or not tabela_sexo:
        return None
    primeiro_nome = nome.strip().split(" ")[0].upper()
    return tabela_sexo.get(primeiro_nome)


def _resolver_sexo(record: dict, tabela_sexo: Dict[str, str]) -> Optional[str]:
    """Decide o Sexo de uma pessoa: prioriza o valor real vindo da base
    de origem; só recorre à estimativa por nome se a base não trouxe
    essa informação para ela."""
    sexo_da_base = _normalizar_sexo_da_base(record.get("sexo"))
    if sexo_da_base:
        return sexo_da_base
    return _calcular_sexo_por_nome(record.get("nome") or "", tabela_sexo)


def write_output(template_path: str | Path, output_path: str | Path, records: List[dict]) -> None:
    if len(records) > (MAX_TEMPLATE_ROW - FIRST_DATA_ROW + 1):
        raise ValueError(
            f"Esse modelo só tem espaço pronto até {MAX_TEMPLATE_ROW - FIRST_DATA_ROW + 1} "
            f"vidas (recebido: {len(records)})."
        )

    wb = openpyxl.load_workbook(template_path, data_only=False, keep_links=True)
    ws = wb[SHEET_NAME]

    tabela_sexo = _carregar_tabela_sexo(wb)

    formula_idade_modelo = ws.cell(row=FORMULA_TEMPLATE_ROW, column=COL_IDADE).value
    formula_faixa_modelo = ws.cell(row=FORMULA_TEMPLATE_ROW, column=COL_FAIXA).value

    for offset, record in enumerate(records):
        linha = FIRST_DATA_ROW + offset
        nome = record.get("nome") or ""

        _set(ws, linha, COL_TDA, record.get("tda") or "")
        _set(ws, linha, COL_NOME, nome)
        _set(ws, linha, COL_SEXO, _resolver_sexo(record, tabela_sexo))
        _set(ws, linha, COL_NASCIMENTO, record.get("nascimento"))
        _set(ws, linha, COL_PLANO, record.get("plano") or "")
        _set(ws, linha, COL_VALOR, record.get("mensalidade"))
        _set(ws, linha, COL_PARENTESCO, record.get("parentesco") or "")
        _set(ws, linha, COL_CIDADE, record.get("cidade") or "")
        _set(ws, linha, COL_UF, record.get("uf") or "")
        _set(ws, linha, COL_SITUACAO, record.get("situacao") or "")
        _set(ws, linha, COL_CID, record.get("cid") or "")
        _set(ws, linha, COL_EMPRESA, record.get("empresa") or "")

        for formula_modelo, col in ((formula_idade_modelo, COL_IDADE), (formula_faixa_modelo, COL_FAIXA)):
            if formula_modelo and isinstance(formula_modelo, str) and formula_modelo.startswith("="):
                _set(ws, linha, col, _formula_para_linha(formula_modelo, linha))

    ultima_escrita = FIRST_DATA_ROW + len(records) - 1
    for linha in range(ultima_escrita + 1, MAX_TEMPLATE_ROW + 1):
        for col in range(1, COL_EMPRESA + 1):
            _set(ws, linha, col, None)

    wb.save(output_path)
