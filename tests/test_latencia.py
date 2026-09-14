# -*- coding: utf-8 -*-
"""
Testes da avaliação de lacuna.

Os casos não são hipotéticos: são as situações reais das cinco fontes do
catálogo, em 14/09/2026. Se algum deles mudar — porque o SISAGUA voltou a
registrar, porque a Anvisa passou a publicar em CSV — o teste falha, e falhar
aqui é a notícia, não o defeito.
"""
from datetime import date

import pytest

from painel_san.modulos.alimento_seguro import fontes, latencia
from painel_san.modulos.alimento_seguro.fontes import Formato
from painel_san.modulos.alimento_seguro.latencia import (
    Amostral, Granularidade, Legibilidade, Observacao, Temporal)

HOJE = date(2026, 9, 14)


# ── a métrica ────────────────────────────────────────────────────────────
def test_em_dia_da_um():
    """Medição há exatamente um período é latência 1,0, por construção."""
    lat = latencia.latencia_relativa(date(2026, 6, 14), 3, HOJE)
    assert 0.98 < lat < 1.02


def test_nunca_medido_e_infinito():
    """Infinito, não um número grande. Não há o que ordenar entre duas fontes que
    nunca mediram."""
    assert latencia.latencia_relativa(None, 12, HOJE) == float("inf")


def test_registro_continuo_nao_acumula_atraso():
    """As monografias da Anvisa são registro, não medição com calendário."""
    assert latencia.latencia_relativa(date(2020, 1, 1), None, HOJE) == 0.0


def test_periodicidade_invalida_levanta():
    with pytest.raises(ValueError, match="positiva"):
        latencia.latencia_relativa(date(2026, 1, 1), 0, HOJE)


def test_folga_evita_alarme_no_dia_seguinte():
    """Fonte semestral que publica com duas semanas de folga está publicando, não
    atrasada. Sem tolerância, tudo fica vermelho e o alerta perde sentido."""
    obs = Observacao(ultima_medicao=date(2026, 3, 1))       # ~6,5 meses
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE)
    assert av.temporal == Temporal.NO_PRAZO


# ── o caso que mais importa acertar ──────────────────────────────────────
def test_ausencia_planejada_nao_e_lacuna():
    """Não há morango no ciclo 2024 porque o plano da Anvisa o marcou para 2025.

    Pintar isso como lacuna destrói a credibilidade do instrumento no primeiro
    leitor que conhecer o cronograma. É a distinção que separa medição de
    denúncia."""
    assert latencia.planejada_para_depois(fontes.PARA_CRONOGRAMA, "morango", 2024)
    obs = Observacao(unidade="morango", planejada_para_depois=True)
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.temporal == Temporal.AUSENCIA_PLANEJADA
    assert not av.tem_alerta, "ausência planejada não pode disparar alerta na célula"
    # O PARA segue ilegível — mas isso é da fonte inteira, não deste alimento.
    assert av.alertas_da_fonte, "a ilegibilidade do PARA continua registrada"


def test_alimento_ja_medido_no_ciclo_nao_e_ausencia_planejada():
    """A abobrinha está marcada para 2024 e foi medida em 2024."""
    assert not latencia.planejada_para_depois(fontes.PARA_CRONOGRAMA, "abobrinha", 2024)


def test_laranja_e_medida_em_todos_os_ciclos():
    """Único alimento dos 36 com medição anual — nunca é ausência planejada."""
    for ciclo in (2023, 2024, 2025):
        assert not latencia.planejada_para_depois(fontes.PARA_CRONOGRAMA, "laranja", ciclo)


def test_fora_do_cronograma_nao_vira_ausencia_planejada():
    """Alimento que não está no plano é outra coisa, e mais grave, que alimento
    planejado para depois. Não pode ser absolvido pelo mesmo caminho."""
    assert not latencia.planejada_para_depois(fontes.PARA_CRONOGRAMA, "acai", 2024)


# ── as dimensões são independentes ───────────────────────────────────────
def test_para_esta_em_dia_e_ainda_assim_ilegivel():
    """O ciclo 2024 é atual. E é PDF. Duas dimensões, dois remédios: publicar em
    CSV não torna a medição mais frequente, nem vice-versa."""
    obs = Observacao(ultima_medicao=date(2025, 12, 1), unidade="pepino")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.temporal == Temporal.NO_PRAZO
    assert av.legibilidade == Legibilidade.ILEGIVEL
    assert av.alertas_da_fonte == (Legibilidade.ILEGIVEL,)
    assert not av.tem_alerta, (
        "ilegibilidade é da fonte, não deste alimento — se contasse como alerta de "
        "célula, os catorze alimentos ficariam vermelhos e o mapa perderia o que varia")


def test_soja_abaixo_do_minimo_da_propria_anvisa():
    """85 amostras contra as 231 que a Anvisa calcula por distribuição binomial.
    A régua é dela, não nossa."""
    obs = Observacao(ultima_medicao=date(2025, 12, 1), n_amostras=85, unidade="soja")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.amostral == Amostral.INSUFICIENTE
    assert "231" in av.motivo and "85" in av.motivo


def test_laranja_atinge_o_minimo():
    obs = Observacao(ultima_medicao=date(2025, 12, 1), n_amostras=240, unidade="laranja")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.amostral == Amostral.SUFICIENTE


def test_sem_minimo_declarado_nao_avalia_amostra():
    """Não inventamos mínimo para quem não declarou um."""
    obs = Observacao(ultima_medicao=date(2026, 3, 1), n_amostras=3)
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE)
    assert av.amostral == Amostral.NAO_AVALIAVEL


def test_granularidade_ausente_nao_e_ausencia_de_dado():
    """O PARA recente não desagrega por UF. O dado existe — só não nesse nível.
    É falha de granularidade, com outro remédio."""
    obs = Observacao(ultima_medicao=date(2025, 12, 1))
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE, eixo_pedido="uf")
    assert av.granularidade == Granularidade.NAO_DESAGREGAVEL
    assert av.temporal == Temporal.NO_PRAZO, "continua em dia; o que falta é o recorte"


def test_ibama_desagrega_por_uf():
    obs = Observacao(ultima_medicao=date(2026, 3, 1))
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE, eixo_pedido="uf")
    assert av.granularidade == Granularidade.DISPONIVEL


# ── a fonte mais atrasada do catálogo ────────────────────────────────────
def test_sisagua_agrotoxicos_parado_desde_2023():
    """Portaria 888/2021 obriga medição trimestral. O registro parou em janeiro de
    2023. É a régua mais dura e o maior descumprimento."""
    obs = Observacao(ultima_medicao=date(2022, 12, 31))
    av = latencia.avaliar(fontes.MS_SISAGUA_AGROTOXICOS, obs, HOJE)
    assert av.temporal == Temporal.ATRASADO
    assert av.latencia_relativa > 14, "mais de 14 trimestres sem medir"
    assert "888" in av.motivo, "o motivo precisa citar a régua e sua origem"


# ── higiene do catálogo ──────────────────────────────────────────────────
def test_ids_sao_unicos():
    ids = [f.id for f in fontes.CATALOGO]
    assert len(ids) == len(set(ids))


def test_toda_fonte_declara_a_origem_da_regua():
    """Régua sem procedência não sustenta afirmação pública. Este teste existe
    para impedir que alguém acrescente uma fonte com periodicidade inventada."""
    for f in fontes.CATALOGO:
        assert f.regua_fonte.strip(), "%s sem regua_fonte" % f.id
        if f.minimo_amostral is not None:
            assert f.regua_minimo, "%s declara mínimo sem dizer de onde vem" % f.id


def test_regua_nao_verificada_esta_sinalizada():
    """Metade do catálogo ainda não teve a régua conferida no documento primário.
    O teste não reprova por isso — registra quais faltam, para não esquecermos."""
    pendentes = [f.id for f in fontes.CATALOGO if not f.regua_verificada]
    assert set(pendentes) == {"ibama_comercializacao", "ms_sisagua_agrotoxicos",
                              "mapa_pncrc"}, (
        "mudou a lista de réguas por verificar: %s" % pendentes)


def test_formato_legivel_e_coerente():
    for f in fontes.CATALOGO:
        assert f.legivel == (f.formato in Formato.LEGIVEIS)


def test_por_id_recupera_e_reclama_do_desconhecido():
    assert fontes.por_id("anvisa_para") is fontes.ANVISA_PARA
    with pytest.raises(KeyError):
        fontes.por_id("nao_existe")


def test_cronograma_do_para_tem_36_alimentos():
    """Os 36 do Plano Plurianual 2023-2025, que somam 80% da aquisição per capita."""
    assert len(fontes.PARA_CRONOGRAMA) == 36
    for alimento, ciclos in fontes.PARA_CRONOGRAMA.items():
        assert ciclos, "%s sem ciclo" % alimento
        assert all(c in (2023, 2024, 2025) for c in ciclos), alimento
