# -*- coding: utf-8 -*-
"""
Testes do mapa de frieza.

Nenhum sobe servidor. A lógica que decide a cor de cada célula é pura e é testada
aqui; a função que desenha é exercitada com plotly, que é dependência do pacote; a
que serve a página em Streamlit não é importada.

Essa separação é o que se testa primeiro — ferramenta web costuma ser reprovada em
revisão de software justamente por não ter uma camada assim.
"""
import os
from datetime import date

import pytest

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro import latencia as lat
from painel_san.modulos.alimento_seguro import pagina, para

HOJE = date(2026, 9, 14)
CSV = os.path.join(os.path.dirname(__file__), "..", "dados", "para_2024.csv")


@pytest.fixture(scope="module")
def celulas():
    return pagina.montar(para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE))


# ── a camada de desenho não contamina a lógica ───────────────────────────
def test_o_modulo_nao_importa_streamlit_ao_ser_carregado():
    """Se importasse, a lógica só rodaria com a interface instalada — e o teste
    da regra viraria teste de servidor. Streamlit nem está neste ambiente."""
    import subprocess, sys
    codigo = ("import sys;"
              "import painel_san.modulos.alimento_seguro.pagina;"
              "sys.exit(1 if 'streamlit' in sys.modules else 0)")
    assert subprocess.call([sys.executable, "-c", codigo]) == 0


# ── os três baldes, e a ordem das perguntas ──────────────────────────────
def test_pendencia_nossa_vem_antes_de_tudo():
    """Se ainda não olhamos, não há afirmação a fazer sobre o órgão. Classificar
    de outro jeito empresta a ele uma falha nossa."""
    av = lat.avaliar(cat.ANVISA_PARA,
                     lat.Observacao(unidade="alface", nao_apurado=True), HOJE)
    assert pagina.balde_de(av) == pagina.Balde.NOSSA


def test_ausencia_planejada_nao_cai_em_lacuna():
    av = lat.avaliar(cat.ANVISA_PARA,
                     lat.Observacao(unidade="morango", planejada_para_depois=True),
                     HOJE)
    assert pagina.balde_de(av) == pagina.Balde.PLANEJADA


def test_abaixo_da_meta_e_lacuna_da_fonte():
    av = lat.avaliar(cat.ANVISA_PARA,
                     lat.Observacao(data_referencia=date(2024, 12, 31),
                                    n_amostras=85, unidade="soja"), HOJE)
    assert pagina.balde_de(av) == pagina.Balde.LACUNA


def test_medido_e_dentro_da_regua_e_o_quarto_caso():
    av = lat.avaliar(cat.ANVISA_PARA,
                     lat.Observacao(data_referencia=date(2024, 12, 31),
                                    n_amostras=240, unidade="laranja"), HOJE)
    assert pagina.balde_de(av) == pagina.Balde.EM_DIA


def test_os_quatro_baldes_cobrem_o_ciclo_sem_sobrar(celulas):
    assert len(celulas) == 36
    assert {c.balde for c in celulas} <= set(pagina.Balde.ORDEM)


def test_o_resumo_nao_soma_os_baldes(celulas):
    """Somar lacuna com pendência nossa daria um número maior e uma afirmação
    falsa — metade da falta seria nossa, apresentada como do órgão."""
    r = pagina.resumo(celulas, HOJE)
    assert r.contagem[pagina.Balde.LACUNA] == 6
    assert r.contagem[pagina.Balde.NOSSA] == 12
    assert r.contagem[pagina.Balde.PLANEJADA] == 10
    assert r.contagem[pagina.Balde.EM_DIA] == 8
    assert r.total == 36
    f = r.frase()
    assert "6 de 36" in f and "12 ainda não apuradas por nós" in f


# ── o que a interface mostra primeiro ────────────────────────────────────
def test_acionaveis_ordenam_da_pior_cobertura_para_a_melhor(celulas):
    """Onde gastar o próximo pedido de informação. A soja, em 37% da meta, é a
    primeira — e é o pior caso documentado do ciclo."""
    tres = pagina.acionaveis(celulas)
    assert len(tres) == 3
    assert tres[0].unidade == "soja"
    coberturas = [c.cobertura_da_meta for c in tres]
    assert coberturas == sorted(coberturas)


def test_acionaveis_so_traz_lacuna_da_fonte(celulas):
    """Não se pede à Anvisa o que falta a nós."""
    for c in pagina.acionaveis(celulas, quantas=10):
        assert c.balde == pagina.Balde.LACUNA


def test_o_resumo_lembra_quais_reguas_faltam_conferir(celulas):
    r = pagina.resumo(celulas, HOJE)
    assert "mapa_pncrc" in r.reguas_por_verificar


def test_o_resumo_carrega_a_data_da_verificacao(celulas):
    """Para dado público, a data de validade é parte da afirmação."""
    assert pagina.resumo(celulas, HOJE).verificado_em == HOJE


# ── cartão de evidência ──────────────────────────────────────────────────
def test_toda_celula_carrega_a_regua_e_sua_origem(celulas):
    """Quem discordar da cor precisa poder ver, na própria célula, contra o que
    ela foi medida. É o que separa painel de instrumento auditável."""
    for c in celulas:
        assert c.regua.strip()
        assert c.motivo.strip()
        assert "Plano Plurianual" in c.regua


def test_o_cartao_diz_o_estado_a_confianca_e_o_motivo(celulas):
    c = [x for x in celulas if x.unidade == "soja"][0]
    txt = pagina.texto_do_cartao(c)
    for pedaco in ("soja", c.estado, c.confianca, "37% da meta", "por quê"):
        assert pedaco in txt


def test_o_cartao_avisa_quando_a_regua_nao_foi_conferida():
    c = pagina.Celula(unidade="x", balde=pagina.Balde.LACUNA, estado="atrasado",
                      confianca="baixa", cobertura_da_meta=None, motivo="m",
                      regua="r", regua_verificada=False)
    assert "não conferida" in pagina.texto_do_cartao(c)


def test_pendencia_nossa_nao_finge_cobertura(celulas):
    for c in celulas:
        if c.balde == pagina.Balde.NOSSA:
            assert c.rotulo_cobertura == "—"


# ── decisões de desenho que são decisões de método ───────────────────────
def test_a_grade_e_alfabetica_e_nao_um_ranking(celulas):
    """Ordenar por gravidade faria a grade parecer ranking de alimentos
    perigosos — leitura que esta fonte não sustenta: o dado é sobre
    irregularidade regulatória, não sobre risco à saúde."""
    nomes = [c.unidade for c, _, _ in pagina.grade(celulas)]
    assert nomes == sorted(nomes)


def test_a_grade_preenche_seis_colunas(celulas):
    pos = pagina.grade(celulas)
    assert len(pos) == 36
    assert {x for _, x, _ in pos} == set(range(6))
    assert len({(x, y) for _, x, y in pos}) == 36, "nenhuma célula sobreposta"


def test_nenhum_balde_e_vermelho():
    """Vermelho é cor de alarme, e alarme é o que este instrumento não emite: ele
    não diz que o alimento está inseguro, diz que o dado não permite saber."""
    for cor in pagina.CORES.values():
        r, g, b = (int(cor[i:i + 2], 16) for i in (1, 3, 5))
        assert not (r > 150 and r > g * 1.8 and r > b * 1.8), "%s puxa para alarme" % cor


def test_cor_nao_e_o_unico_codigo():
    """Parte dos leitores não distingue cor, e o painel será impresso em preto e
    branco em alguma banca. Forma e cor juntas dão quatro combinações distintas."""
    assert set(pagina.SIMBOLOS) == set(pagina.CORES) == set(pagina.Balde.ORDEM)
    combinacoes = {(pagina.SIMBOLOS[b], pagina.CORES[b]) for b in pagina.Balde.ORDEM}
    assert len(combinacoes) == len(pagina.Balde.ORDEM)


def test_nenhum_simbolo_e_aberto():
    """Defeito visto na primeira renderização: símbolo "-open" no Plotly ignora a
    cor de preenchimento e desenha só o contorno. As doze pendências nossas — o
    MAIOR grupo do painel — saíram brancas sobre fundo branco, invisíveis.

    O grupo que o instrumento usa para se cobrar não pode ser o único que some."""
    for balde, simbolo in pagina.SIMBOLOS.items():
        assert "open" not in simbolo, "%s ficaria sem preenchimento" % balde


def test_todo_balde_tem_contorno_proprio():
    assert set(pagina.CONTORNOS) == set(pagina.Balde.ORDEM)


# ── a figura ─────────────────────────────────────────────────────────────
def test_a_figura_tem_uma_serie_por_balde_presente(celulas):
    fig = pagina.figura(celulas)
    nomes = [t.name for t in fig.data]
    assert len(nomes) == 4
    for balde in pagina.Balde.ORDEM:
        assert any(n.startswith(balde) for n in nomes)


def test_a_legenda_traz_a_contagem(celulas):
    """A leitura começa pelo agregado; um mapa inteiro em alerta é ignorado."""
    fig = pagina.figura(celulas)
    assert any("(6)" in t.name for t in fig.data), "seis lacunas da fonte"
    assert any("(12)" in t.name for t in fig.data), "doze pendências nossas"


def test_a_figura_leva_o_cartao_em_cada_ponto(celulas):
    fig = pagina.figura(celulas)
    total = sum(len(t.hovertext) for t in fig.data)
    assert total == 36
    assert all("régua" in h for t in fig.data for h in t.hovertext)
