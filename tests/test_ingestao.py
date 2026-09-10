# -*- coding: utf-8 -*-
"""
Testes da ingestão.

Dois tipos convivem aqui:

  UNITÁRIOS — exercitam o cálculo com uma tabela de seis linhas montada à mão, com
  números que dá para conferir de cabeça. Não tocam disco e não precisam de nada
  do IBGE.

  DE CONTRATO — validam o Parquet versionado em dados/processado. É o tipo de
  teste que teria pego, sozinho, o defeito de arredondamento que fez 40 células do
  painel divergirem do SIDRA: nenhuma função estava errada isoladamente, mas o
  produto final violava um invariante.
"""
import os

import pandas as pd
import pytest

from painel_san.modulos.san import ingestao

AQUI = os.path.dirname(os.path.abspath(__file__))
PROCESSADO = os.path.join(os.path.dirname(AQUI), "dados", "processado")

UFS_ESPERADAS = 27
GRUPOS = (1, 2, 3, 4)


# ── unitários ────────────────────────────────────────────────────────────
@pytest.fixture
def tabela():
    """Seis linhas, números redondos.

    Brasil 2018: NOVA 1 com 10.000 kcal e NOVA 4 com 10.000 → 50% cada.
    Sergipe 2018: NOVA 1 com 30.000 e NOVA 4 com 10.000 → 75% e 25%.
    Mais uma linha de grupo, que não pode entrar em conta nenhuma.
    """
    return pd.DataFrame([
        # categoria,             localidade, periodo, valor, grupo, kcal
        ("1.1.1 Arroz",          "Brasil",   "2018",   10.0,   1,   100),
        ("6.3.1 Biscoito",       "Brasil",   "2018",    5.0,   4,   200),
        ("1.1.1 Arroz",          "Sergipe",  "2018",   30.0,   1,   100),
        ("6.3.1 Biscoito",       "Sergipe",  "2018",    5.0,   4,   200),
        ("1. Cereais",           "Brasil",   "2018",  999.0,   1,   100),
        ("1.1 Cereais e afins",  "Brasil",   "2018",  999.0,   1,   100),
    ], columns=["categoria_1", "localidade_nome", "periodo", "valor",
                "nova_grupo", "kcal_por_100g"]).assign(
        kcal_pc_ano=lambda d: d["valor"] * d["kcal_por_100g"] * 10)


def test_apenas_folhas_descarta_linhas_de_grupo(tabela):
    """As linhas de grupo são somatórios da própria tabela. Se entrarem, o mesmo
    alimento é contado duas vezes e o denominador infla."""
    folhas = ingestao.apenas_folhas(tabela)
    assert len(folhas) == 4
    assert set(folhas["categoria_1"]) == {"1.1.1 Arroz", "6.3.1 Biscoito"}


def test_participacao_calorica_brasil(tabela):
    folhas = ingestao.apenas_folhas(tabela)
    br = ingestao.participacao_calorica(
        folhas[folhas["localidade_nome"] == "Brasil"], ["periodo"])
    pct = dict(zip(br["nova_grupo"], br["pct_calorias"]))
    assert pct == {1: 50.0, 4: 50.0}
    assert br["kcal_total"].iloc[0] == 20000.0


def test_participacao_calorica_por_uf(tabela):
    folhas = ingestao.apenas_folhas(tabela)
    uf = ingestao.participacao_calorica(
        folhas[folhas["localidade_nome"] == "Sergipe"],
        ["localidade_nome", "periodo"])
    pct = dict(zip(uf["nova_grupo"], uf["pct_calorias"]))
    assert pct == {1: 75.0, 4: 25.0}


def test_agregar_nao_mistura_niveis(tabela):
    """Brasil, região e UF convivem na mesma coluna da tabela do SIDRA. Se o
    Brasil entrar na conta das UFs, cada alimento é contado duas vezes."""
    quadros = ingestao.agregar(ingestao.apenas_folhas(tabela))
    # O recorte Brasil agrega só por período, então nem carrega localidade_nome.
    assert "localidade_nome" not in quadros["brasil"].columns
    assert set(quadros["uf"]["localidade_nome"]) == {"Sergipe"}
    assert quadros["regiao"].empty, "nenhuma região na tabela de brinquedo"
    # O Brasil nao pode ter vazado para o quadro de UF: seriam 40.000 kcal em vez
    # de 40.000 so de Sergipe.
    assert quadros["uf"]["kcal_total"].iloc[0] == 40000.0


def test_preparar_exige_colunas():
    with pytest.raises(ValueError, match="colunas ausentes"):
        ingestao.preparar(pd.DataFrame({"categoria_1": ["x"]}))


def test_preparar_descarta_valor_nao_numerico():
    df = pd.DataFrame({"categoria_1": ["1.1.1 Arroz", "1.1.2 Feijão"],
                       "localidade_nome": ["Brasil", "Brasil"],
                       "periodo": ["2018", "2018"],
                       "valor": ["10.5", "..."]})
    saida = ingestao.preparar(df)
    assert len(saida) == 1
    assert saida["valor"].iloc[0] == 10.5


# ── contrato sobre o dado versionado ─────────────────────────────────────
@pytest.fixture(scope="module")
def quadros():
    arquivos = {n: os.path.join(PROCESSADO, "nova_%s.parquet" % n)
                for n in ("brasil", "regiao", "uf", "mapa")}
    faltando = [n for n, c in arquivos.items() if not os.path.exists(c)]
    if faltando:
        pytest.skip("dados/processado incompleto: %s" % faltando)
    return {n: pd.read_parquet(c) for n, c in arquivos.items()}


def test_contrato_colunas(quadros):
    for nivel in ("brasil", "regiao", "uf"):
        esperadas = {"periodo", "nova_grupo", "kcal_nova", "kcal_total",
                     "pct_calorias", "nova_rotulo"}
        if nivel != "brasil":
            esperadas.add("localidade_nome")
        assert esperadas <= set(quadros[nivel].columns), nivel


def test_contrato_percentuais_no_intervalo(quadros):
    for nivel in ("brasil", "regiao", "uf"):
        pct = quadros[nivel]["pct_calorias"]
        assert pct.between(0, 100).all(), "%s tem percentual fora de 0-100" % nivel


def test_contrato_grupos_somam_cem(quadros):
    """Os quatro grupos NOVA repartem 100% das calorias. A tolerância de 0,4 p.p.
    cobre o arredondamento a uma casa em quatro parcelas."""
    for nivel, chaves in (("brasil", ["periodo"]),
                          ("regiao", ["localidade_nome", "periodo"]),
                          ("uf", ["localidade_nome", "periodo"])):
        somas = quadros[nivel].groupby(chaves)["pct_calorias"].sum()
        fora = somas[(somas - 100).abs() > 0.4]
        assert fora.empty, "%s: %s" % (nivel, fora.to_dict())


def test_contrato_quatro_grupos_por_recorte(quadros):
    for nivel, chaves in (("brasil", ["periodo"]),
                          ("regiao", ["localidade_nome", "periodo"]),
                          ("uf", ["localidade_nome", "periodo"])):
        por_recorte = quadros[nivel].groupby(chaves)["nova_grupo"].apply(
            lambda s: tuple(sorted(s)))
        errados = por_recorte[por_recorte != GRUPOS]
        assert errados.empty, "%s: recorte sem os 4 grupos: %s" % (nivel, errados.to_dict())


def test_contrato_27_ufs(quadros):
    assert quadros["uf"]["localidade_nome"].nunique() == UFS_ESPERADAS


def test_contrato_cinco_regioes(quadros):
    assert quadros["regiao"]["localidade_nome"].nunique() == 5


def test_contrato_tres_periodos(quadros):
    for nivel in ("brasil", "regiao", "uf"):
        assert set(quadros[nivel]["periodo"]) == {"2002", "2008", "2018"}, nivel


def test_contrato_mapa_sem_kcal_zero_indevido(quadros):
    """Reflete, sobre o dado gravado, o mesmo invariante que nova.py testa sobre a
    função: kcal zero faz o alimento sumir do cálculo em silêncio."""
    import re
    mapa = quadros["mapa"]
    folhas = mapa[mapa["categoria_1"].str.match(r"^\d+\.\d+\.\d+")]
    zerados = folhas[folhas["kcal_por_100g"] == 0]["categoria_1"].tolist()
    # Sal, vinagre e água não têm energia; kcal zero neles é correto.
    permitido = re.compile(r"(?i)(^|[^a-zà-ú])(sal|vinagre|água|agua)([^a-zà-ú]|$)")
    indevidos = [c for c in zerados if not permitido.search(c)]
    assert not indevidos, "alimentos com kcal zero somem do cálculo: %s" % indevidos


def test_contrato_ultraprocessados_crescem(quadros):
    """A série nacional de NOVA 4 cresce em todo o período. Não é lei da natureza,
    é o achado central da dissertação — se um dia inverter, é sinal de que algo no
    pipeline mudou, e o teste obriga a olhar."""
    br = quadros["brasil"]
    n4 = br[br["nova_grupo"] == 4].sort_values("periodo")["pct_calorias"].tolist()
    assert n4 == sorted(n4), "NOVA 4 deixou de crescer: %s" % n4
