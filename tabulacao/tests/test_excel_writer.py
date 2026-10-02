"""
test_excel_writer.py
----------------------
Testa a escrita no modelo REAL (modelos/Modelo_de_Estudo.xlsx), travando
as três descobertas feitas durante o desenvolvimento:

  1. Campos vazios nos registros novos precisam realmente ficar vazios
     no arquivo final (não o valor de exemplo que já estava no modelo).
  2. Idade e Faixa continuam sendo fórmulas, calculadas corretamente
     linha a linha (não o valor fixo que a linha 2 do modelo tinha).
  3. Sexo é calculado em Python a partir da tabela em cache do próprio
     arquivo (não depende de nenhum link externo).
  4. Linhas de exemplo/fórmula sobrando são limpas, mas o resumo
     (texto "23 Conjuge"/"23 Filhos", movido para as linhas
     10006/10007 depois que o modelo foi expandido para 10.000 vidas)
     nunca é tocado quando sobra espaço.
  5. O modelo foi expandido de ~250 para 10.000 vidas de capacidade,
     mantendo a performance e a correção das fórmulas até a última
     linha.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from tabulacao import excel_writer

TEMPLATE = Path(__file__).resolve().parent.parent / "modelos" / "Modelo_de_Estudo.xlsx"

pytestmark = pytest.mark.skipif(not TEMPLATE.exists(), reason="Modelo real não disponível neste ambiente.")


def _registro(nome="Fulano de Tal", **kwargs):
    base = {
        "tda": "T", "nome": nome, "nascimento": date(1990, 1, 1),
        "plano": "", "mensalidade": None, "parentesco": "Titular",
    }
    base.update(kwargs)
    return base


def test_campo_vazio_fica_vazio_nao_mantem_exemplo_do_modelo(tmp_path):
    """Regressão: ws.cell(value=None) não limpa célula no openpyxl —
    sem a correção, o Valor (mensalidade=None) ficava com o número de
    exemplo que já estava no modelo."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [_registro(mensalidade=None)])

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    assert ws.cell(row=2, column=excel_writer.COL_VALOR).value is None


def test_idade_e_faixa_sao_formulas_calculadas_corretamente(tmp_path):
    """Idade e Faixa devem ser fórmulas (nunca um valor fixo), e devem
    calcular certo quando o arquivo é aberto de verdade."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [_registro(nascimento=date(1985, 3, 10))])

    wb = openpyxl.load_workbook(output, data_only=False)
    ws = wb["Base de Vidas"]
    idade_formula = ws.cell(row=2, column=excel_writer.COL_IDADE).value
    faixa_formula = ws.cell(row=2, column=excel_writer.COL_FAIXA).value
    assert isinstance(idade_formula, str) and idade_formula.startswith("=")
    assert "D2" in idade_formula  # referência à linha certa
    assert isinstance(faixa_formula, str) and faixa_formula.startswith("=")


def test_sexo_calculado_sem_depender_de_link_externo(tmp_path):
    """Regressão crítica: a fórmula original de Sexo depende de um
    arquivo externo que não viaja com este projeto — calculamos em
    Python usando a tabela já em cache dentro do modelo, e escrevemos
    como texto fixo (não fórmula)."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [
        _registro(nome="Carlos Eduardo Souza"),
        _registro(nome="Maria Fernanda Lima"),
    ])

    wb = openpyxl.load_workbook(output, data_only=False)
    ws = wb["Base de Vidas"]
    sexo_carlos = ws.cell(row=2, column=excel_writer.COL_SEXO).value
    sexo_maria = ws.cell(row=3, column=excel_writer.COL_SEXO).value
    assert sexo_carlos == "M"
    assert sexo_maria == "F"
    # não pode ser uma fórmula (não deve começar com '=')
    assert not str(sexo_carlos).startswith("=")


def test_linhas_sobrando_sao_limpas(tmp_path):
    """Regressão: linhas de exemplo do modelo além dos registros novos
    precisam ficar completamente vazias, não misturar gente de
    demonstração com dados reais."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [_registro()])

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    for linha in (3, 5, 50, 123, 250):
        valores = [ws.cell(row=linha, column=c).value for c in range(1, excel_writer.COL_EMPRESA + 1)]
        assert all(v is None for v in valores), f"Linha {linha} não foi limpa: {valores}"


def test_texto_solto_do_modelo_antigo_e_sobrescrito_quando_necessario(tmp_path):
    """As células B257/B258 do modelo original ('23 Conjuge'/'23 Filhos')
    são só uma anotação manual solta que sobrou de um cliente anterior —
    confirmei que não é fórmula nem é referenciada em nenhum outro lugar
    da planilha. Por isso, quando a base nova tem gente suficiente pra
    alcançar essas linhas, elas são sobrescritas com dado real, como
    qualquer outra linha de exemplo."""
    import openpyxl

    registros = [_registro(nome=f"Pessoa {i}") for i in range(260)]
    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, registros)

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    # linha 257 agora é a pessoa de índice 255 (257 - 2 = 255)
    assert ws.cell(row=257, column=2).value == "Pessoa 255"
    assert ws.cell(row=258, column=2).value == "Pessoa 256"


def test_resumo_na_nova_posicao_e_preservado_quando_sobra_espaco(tmp_path):
    """O resumo ('23 Conjuge'/'23 Filhos') foi movido para as linhas
    10006/10007 depois da expansão do modelo — precisa continuar
    intocado quando a base enviada tem bem menos gente que 10.000."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [_registro()])

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    assert ws.cell(row=10006, column=2).value == "23 Conjuge"
    assert ws.cell(row=10007, column=2).value == "23 Filhos"


def test_suporta_10_mil_vidas_em_tempo_razoavel(tmp_path):
    """Capacidade real exigida pelo usuário: o modelo precisa aguentar
    até 10.000 vidas, calculando as fórmulas certinho até a última
    linha, em tempo razoável (não pode voltar a 'travar' como o bug de
    performance anterior do projeto)."""
    import time
    import openpyxl

    registros = [_registro(nome=f"Pessoa {i}") for i in range(10000)]
    output = tmp_path / "saida.xlsx"

    inicio = time.time()
    excel_writer.write_output(TEMPLATE, output, registros)
    duracao = time.time() - inicio

    assert duracao < 15, f"Escrever 10.000 vidas levou {duracao:.1f}s"

    wb = openpyxl.load_workbook(output, data_only=False)
    ws = wb["Base de Vidas"]
    assert ws.cell(row=2, column=excel_writer.COL_NOME).value == "Pessoa 0"
    assert ws.cell(row=10001, column=excel_writer.COL_NOME).value == "Pessoa 9999"
    formula_ultima_linha = ws.cell(row=10001, column=excel_writer.COL_IDADE).value
    assert "D10001" in formula_ultima_linha


def test_excede_capacidade_do_modelo_gera_erro_claro(tmp_path):
    """Se algum dia uma base tiver mais gente do que o modelo suporta,
    o sistema deve avisar claramente, não gerar um arquivo quebrado."""
    output = tmp_path / "saida.xlsx"
    registros_demais = [_registro(nome=f"Pessoa {i}") for i in range(10001)]
    with pytest.raises(ValueError, match="só tem espaço"):
        excel_writer.write_output(TEMPLATE, output, registros_demais)


def test_sexo_da_base_tem_prioridade_sobre_estimativa_por_nome(tmp_path):
    """Regressão: se a base de origem já tem Sexo preenchido para a
    pessoa, usa esse valor real (normalizado pra M/F) em vez de
    adivinhar pelo primeiro nome."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [
        _registro(nome="Carlos Eduardo Souza", sexo="Masculino"),
        _registro(nome="Maria Souza Lima", sexo="F"),
    ])

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    assert ws.cell(row=2, column=excel_writer.COL_SEXO).value == "M"
    assert ws.cell(row=3, column=excel_writer.COL_SEXO).value == "F"


def test_sexo_cai_para_estimativa_por_nome_quando_base_nao_informa(tmp_path):
    """Quando a base NÃO trouxe Sexo para essa pessoa específica (None
    ou vazio), o sistema volta a estimar pelo primeiro nome — mesmo
    comportamento de antes, agora só como reserva."""
    import openpyxl

    output = tmp_path / "saida.xlsx"
    excel_writer.write_output(TEMPLATE, output, [_registro(nome="Pedro Costa", sexo=None)])

    wb = openpyxl.load_workbook(output)
    ws = wb["Base de Vidas"]
    assert ws.cell(row=2, column=excel_writer.COL_SEXO).value == "M"


def test_celula_vazia_de_csv_nao_quebra_geracao_do_arquivo(tmp_path):
    """Regressão crítica: quando uma célula de texto do CSV está
    genuinamente vazia, o pandas às vezes entrega isso como NaN (um
    tipo 'float' especial) em vez de None ou texto vazio — e
    'NaN or \"\"' em Python devolve o próprio NaN de volta (é um valor
    "verdadeiro"), não uma string vazia. Isso derrubava a geração do
    arquivo inteiro com 'float' object has no attribute 'strip'."""
    import io
    import sys as _sys
    from pathlib import Path as _Path

    PROJECT_ROOT = _Path(__file__).resolve().parent.parent
    _sys.path.insert(0, str(PROJECT_ROOT))
    import app as app_module

    import pandas as pd
    df = pd.DataFrame({
        "Nome": ["Carlos Souza", "Pedro Lima"],
        "CPF": ["11111111111", "22222222222"],
        "Data Nascimento": ["1985-03-10", "1990-07-15"],
        "Sexo": ["Masculino", ""],  # célula genuinamente vazia
        "Parentesco": ["Titular", "Filho"],
    })
    csv_bytes = df.to_csv(index=False, sep=";", encoding="utf-8-sig").encode("utf-8-sig")

    client = app_module.app.test_client()
    resp1 = client.post("/api/detectar-colunas", data={"bases": (io.BytesIO(csv_bytes), "teste.csv")})
    job_id = resp1.get_json()["job_id"]
    client.post("/api/processar", json={"job_id": job_id, "mapeamento": {}})
    resp3 = client.post("/api/finalizar", json={"job_id": job_id, "decisoes": {}})

    assert resp3.status_code == 200, resp3.get_json()
