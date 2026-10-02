"""
test_dedup_seguranca.py
--------------------------
Testa a regra de segurança: SÓ remove automaticamente quando nome
exato + nascimento + CPF batem os TRÊS ao mesmo tempo. Qualquer outra
coincidência (mesmo com 2 dos 3 critérios) precisa de revisão humana.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from tabulacao import pipeline, dedup


def _salvar_csv(tmp_path, df, nome="teste.csv"):
    path = tmp_path / nome
    df.to_csv(path, index=False, sep=";", encoding="utf-8-sig")
    return str(path)


def test_tres_fatores_iguais_e_confirmada_e_removida(tmp_path):
    df = pd.DataFrame({
        "Nome": ["Ana Paula Lima", "Ana Paula Lima"],
        "CPF": ["11111111111", "11111111111"],
        "Data Nascimento": ["1990-01-01", "1990-01-01"],
        "Matricula": ["1", "1"],
        "Parentesco": ["Titular", "Titular"],
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.confirmed_duplicates_pairs == 1
    assert resultado.possible_duplicates_pairs == 0
    assert len(pipeline.resolve_confirmed_duplicates(resultado)) == 1


def test_mesmo_cpf_e_nome_mas_nascimento_diferente_nao_e_confirmada(tmp_path):
    """Regressão do pedido do usuário: mesmo com 2 dos 3 critérios
    batendo (CPF e nome), se o nascimento for diferente, NUNCA pode
    remover sozinho."""
    df = pd.DataFrame({
        "Nome": ["Carlos Souza", "Carlos Souza"],
        "CPF": ["22222222222", "22222222222"],
        "Data Nascimento": ["1985-05-05", "1999-09-09"],
        "Matricula": ["2", "2"],
        "Parentesco": ["Titular", "Titular"],
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.confirmed_duplicates_pairs == 0
    assert resultado.possible_duplicates_pairs == 1
    assert len(pipeline.resolve_confirmed_duplicates(resultado)) == 2  # ninguém removido sozinho


def test_mesma_matricula_nomes_parecidos_cpf_diferente_nao_e_confirmada(tmp_path):
    """Matrícula reaproveitada: nunca remove sozinho."""
    df = pd.DataFrame({
        "Nome": ["Diego Martins", "Diego Martins Junior"],
        "CPF": ["44444444444", "55555555555"],
        "Data Nascimento": ["1975-03-03", "1975-03-03"],
        "Matricula": ["9999", "9999"],
        "Parentesco": ["Titular", "Titular"],
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.confirmed_duplicates_pairs == 0
    assert resultado.possible_duplicates_pairs == 1
    assert len(pipeline.resolve_confirmed_duplicates(resultado)) == 2


def test_nomes_muito_parecidos_sem_nenhum_outro_sinal_nunca_e_confirmada():
    df = pd.DataFrame({
        "_nome": ["João da Silva", "João da Silva Junior"],
        "_cpf": [None, None],
        "_matricula": [None, None],
        "_nascimento": [None, None],
    })
    resultado = dedup.find_duplicates(df)
    confirmadas = [p for p in resultado.pairs if p.status.value == "confirmada"]
    assert confirmadas == []


def test_bloco_gigante_de_nomes_parecidos_e_pulado_sem_travar(tmp_path):
    """Regressão crítica de performance: um bloco com milhares de
    pessoas cujo nome começa igual (ex.: 2.500 variações de 'João
    Silva' numa base sintética, ou um sobrenome muito comum numa base
    real grande) não pode travar o processamento — nesse volume, a
    comparação par a par é pulada (ver MAX_BLOCO_FUZZY em dedup.py)."""
    import time

    linhas = []
    for i in range(2500):
        linhas.append({
            "Nome": f"João Silva {i}", "CPF": f"{i:011d}",
            "Data Nascimento": "1990-01-01", "Matricula": str(i), "Parentesco": "Titular",
        })
    path = _salvar_csv(tmp_path, pd.DataFrame(linhas), "base_bloco_gigante.csv")

    inicio = time.time()
    resultado = pipeline.process_sources([path])
    duracao = time.time() - inicio

    assert duracao < 10, f"Processar esse cenário levou {duracao:.1f}s"
    # bloco maior que MAX_BLOCO_FUZZY -> comparação pulada -> 0 pares
    # vindos desse grupo especificamente (sem isso, seriam ~3 milhões
    # de comparações só aqui)
    assert resultado.possible_duplicates_pairs == 0


def test_processamento_de_base_grande_e_rapido(tmp_path):
    """Regressão de performance: precisa continuar rápido mesmo com a
    regra de 3 fatores (o agrupamento continua O(n), não O(n²))."""
    import random
    import time

    nomes = ["João Silva", "Maria Souza", "Pedro Santos", "Ana Oliveira", "Carlos Lima"]
    linhas = []
    for i in range(1000):
        linhas.append({
            "Nome": f"{random.choice(nomes)} {i}",
            "CPF": f"{i:011d}",
            "Data Nascimento": "1990-01-01",
            "Matricula": str(i),
            "Parentesco": "Titular",
        })
    path = _salvar_csv(tmp_path, pd.DataFrame(linhas), "base_grande.csv")

    inicio = time.time()
    resultado = pipeline.process_sources([path])
    duracao = time.time() - inicio

    assert resultado.records_found == 1000
    assert duracao < 5, f"Processar 1000 pessoas levou {duracao:.1f}s"


def test_nome_e_nascimento_iguais_confirma_quando_base_nao_tem_cpf(tmp_path):
    """Nova regra: se a base enviada não tem coluna de CPF nenhuma,
    nome + nascimento exatamente iguais já é critério suficiente para
    confirmar e remover sozinho (sem CPF disponível, é o sinal mais
    forte que dá pra verificar)."""
    df = pd.DataFrame({
        "Nome": ["Ana Paula Lima", "Ana Paula Lima"],
        "Data Nascimento": ["1990-01-01", "1990-01-01"],
        "Parentesco": ["Titular", "Titular"],
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.confirmed_duplicates_pairs == 1
    assert resultado.possible_duplicates_pairs == 0
    assert len(pipeline.resolve_confirmed_duplicates(resultado)) == 1


def test_nome_e_nascimento_iguais_NAO_confirma_quando_base_tem_cpf_mas_faltou_nesse_par(tmp_path):
    """Regressão: se a base TEM coluna de CPF (só que vazia para esse
    par específico), nome + nascimento iguais sozinhos NÃO bastam para
    confirmar — precisa ir para revisão, porque o CPF pode só ter sido
    esquecido de preencher para essas duas pessoas, não ausente da
    base inteira."""
    df = pd.DataFrame({
        "Nome": ["Ana Paula Lima", "Ana Paula Lima", "Pedro Costa"],
        "CPF": ["", "", "11111111111"],
        "Data Nascimento": ["1990-01-01", "1990-01-01", "1980-01-01"],
        "Parentesco": ["Titular", "Titular", "Titular"],
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.confirmed_duplicates_pairs == 0
    assert resultado.possible_duplicates_pairs == 1
    assert len(pipeline.resolve_confirmed_duplicates(resultado)) == 3  # ninguém removido sozinho


def test_tda_e_deduzido_do_parentesco_quando_base_nao_tem_coluna_de_tipo(tmp_path):
    """Regressão: a maioria das bases de RH só tem 'Parentesco', nunca
    uma coluna separada dizendo Titular/Dependente — o sistema precisa
    deduzir isso sozinho a partir do Parentesco."""
    df = pd.DataFrame({
        "Nome": ["Carlos Souza", "Maria Lima", "Pedro Lima"],
        "CPF": ["11111111111", "22222222222", "33333333333"],
        "Data Nascimento": ["1985-03-10", "1990-07-15", "2015-11-22"],
        "Parentesco": ["Titular", "Cônjuge", "Filho"],
        "Plano": ["Plano A"] * 3,
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    tda_por_nome = dict(zip(resultado.df_clean["_nome"], resultado.df_clean["_tda"]))
    assert tda_por_nome["Carlos Souza"] == "T"
    assert tda_por_nome["Maria Lima"] == "D"
    assert tda_por_nome["Pedro Lima"] == "D"


def test_tda_explicito_na_base_tem_prioridade_sobre_deducao(tmp_path):
    """Se a base JÁ tem uma coluna de Tipo/T-D-A, usa ela — não
    sobrescreve com a dedução por Parentesco."""
    df = pd.DataFrame({
        "Nome": ["Carlos Souza"],
        "CPF": ["11111111111"],
        "Data Nascimento": ["1985-03-10"],
        "Parentesco": ["Titular"],
        "Tipo": ["A"],  # Agregado, por exemplo — não seria deduzido do Parentesco
    })
    resultado = pipeline.process_sources([_salvar_csv(tmp_path, df)])
    assert resultado.df_clean["_tda"].iloc[0] == "A"
