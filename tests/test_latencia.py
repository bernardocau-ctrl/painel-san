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
    Amostral, Base, Confianca, Granularidade, Legibilidade, Observacao, Temporal)

HOJE = date(2026, 9, 14)


# ── a métrica ────────────────────────────────────────────────────────────
def test_em_dia_da_um():
    """Medição há exatamente um período é latência 1,0, por construção."""
    lat = latencia.latencia_relativa(date(2026, 6, 14), 3, HOJE)
    assert 0.98 < lat < 1.02


def test_sem_data_e_infinito():
    """Infinito, não um número grande. Não há o que ordenar entre duas fontes das
    quais nada se localizou."""
    assert latencia.latencia_relativa(None, 12, HOJE) == float("inf")


def test_registro_continuo_nao_acumula_atraso():
    """As monografias da Anvisa são registro, não medição com calendário."""
    assert latencia.latencia_relativa(date(2020, 1, 1), None, HOJE) == 0.0


def test_periodicidade_invalida_levanta():
    with pytest.raises(ValueError, match="positiva"):
        latencia.latencia_relativa(date(2026, 1, 1), 0, HOJE)


# ── medir não é publicar ─────────────────────────────────────────────────
def test_publicacao_tem_precedencia_sobre_referencia():
    """De fora do órgão só a publicação é verificável. Quando as duas existem, é
    a publicação que sustenta a classificação — e a avaliação registra isso."""
    obs = Observacao(data_referencia=date(2024, 12, 31),
                     data_publicacao=date(2025, 11, 30))
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.base_temporal == Base.PUBLICACAO
    assert "2025-11-30" in av.motivo


def test_so_referencia_enfraquece_a_afirmacao():
    """Com apenas a data de referência, o instrumento não sabe se o resultado
    chegou a ser publicado — e o texto precisa dizer isso, não escondê-lo."""
    obs = Observacao(data_referencia=date(2024, 12, 31))
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.base_temporal == Base.REFERENCIA
    assert "publicação desconhecida" in av.motivo


def test_as_duas_datas_produzem_latencias_diferentes():
    """É o caso que motivou a separação: o dado é de 2022, mas só apareceu em
    2025. Confundir as duas responde a pergunta errada."""
    obs = Observacao(data_referencia=date(2022, 12, 31),
                     data_publicacao=date(2025, 6, 30))
    lat_ref = latencia.latencia_relativa(obs.data_referencia, 36, HOJE)
    lat_pub = latencia.latencia_relativa(obs.data_publicacao, 36, HOJE)
    assert lat_ref > lat_pub
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.latencia_relativa == pytest.approx(lat_pub)


def test_o_modulo_nunca_afirma_que_o_orgao_nao_mediu():
    """Regra de redação, com teste, porque é a afirmação que derruba o
    instrumento. Nada localizado é sobre o recurso consultado, não sobre o país."""
    obs = Observacao(unidade="acai")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.temporal == Temporal.NADA_LOCALIZADO
    assert "não permite concluir" in av.motivo
    for proibida in ("deixou de monitorar", "não mediu", "não existe", "nunca medido"):
        assert proibida not in av.motivo


# ── tolerância em dias, declarada por fonte ──────────────────────────────
def test_tolerancia_evita_alarme_no_dia_seguinte():
    """Fonte anual que publica com seis semanas de folga está publicando, não
    atrasada. Sem tolerância, tudo fica vermelho e o alerta perde sentido."""
    obs = Observacao(data_publicacao=date(2025, 8, 1))       # ~13,5 meses
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE)
    assert av.temporal == Temporal.PENDENTE
    assert not av.tem_alerta, "pendente dentro da tolerância não pinta a célula"


def test_a_tolerancia_nao_e_mais_fracao_fixa_do_prazo():
    """O defeito que motivou a troca, travado como teste.

    Com 15% do prazo para todos, quanto mais longo o compromisso, maior a folga
    absoluta — o PARA ganhava ~164 dias e o IBAMA ~27. Agora a fração cai
    conforme o prazo cresce: quem promete pouco tempo tem mais margem
    proporcional, porque um mês de atraso num semestre pesa menos que dois meses
    num triênio."""
    fracoes = sorted(
        (f.periodicidade_meses, f.tolerancia_dias / (f.periodicidade_meses * 30.44))
        for f in fontes.CATALOGO if f.tem_calendario)
    assert len(fracoes) >= 3
    assert len(set(round(x, 3) for _, x in fracoes)) > 1, (
        "se todas as frações fossem iguais, teríamos reinventado a régua percentual")
    # prazo mais curto do catálogo tem fração maior que o mais longo
    assert fracoes[0][1] > fracoes[-1][1]


def test_atraso_prolongado_se_distingue_de_atraso():
    """Um ciclo perdido e catorze ciclos perdidos não podem ter a mesma cor."""
    um_pouco = Observacao(data_publicacao=date(2025, 11, 1))  # ~4,4 meses além do prazo
    muito = Observacao(data_publicacao=date(2022, 12, 31))    # ~7 semestres além
    a = latencia.avaliar(fontes.MS_SISAGUA_AGROTOXICOS, um_pouco, HOJE)
    b = latencia.avaliar(fontes.MS_SISAGUA_AGROTOXICOS, muito, HOJE)
    assert a.temporal == Temporal.ATRASADO
    assert b.temporal == Temporal.ATRASO_PROLONGADO
    assert b.latencia_relativa > a.latencia_relativa
    assert a.tem_alerta and b.tem_alerta, "os dois alertam; o que muda é a gravidade"


def test_toda_fonte_com_calendario_declara_tolerancia_e_justificativa():
    """Impede que alguém acrescente fonte com tolerância inventada e muda — este
    é o único número do catálogo que é NOSSO, e por isso precisa de defesa
    escrita ao lado."""
    for f in fontes.CATALOGO:
        if not f.tem_calendario:
            continue
        assert f.tolerancia_dias, "%s sem tolerância declarada" % f.id
        assert f.regua_tolerancia.strip(), "%s sem justificativa" % f.id
        assert "nossa" in f.regua_tolerancia.lower(), (
            "%s precisa dizer que a tolerância é escolha nossa, não do órgão" % f.id)


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
    obs = Observacao(data_publicacao=date(2025, 12, 1), unidade="pepino")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.temporal == Temporal.NO_PRAZO
    assert av.legibilidade == Legibilidade.ILEGIVEL
    assert av.alertas_da_fonte == (Legibilidade.ILEGIVEL,)
    assert not av.tem_alerta, (
        "ilegibilidade é da fonte, não deste alimento — se contasse como alerta de "
        "célula, os catorze alimentos ficariam vermelhos e o mapa perderia o que varia")


# ── cobertura da meta, não "insuficiente" ────────────────────────────────
def test_soja_fica_abaixo_da_meta_da_propria_anvisa():
    """85 amostras contra as 231 que a Anvisa calcula por distribuição binomial.
    A régua é dela, não nossa — e o que se afirma é cobertura da meta, não
    insuficiência estatística, que seria conclusão nossa."""
    obs = Observacao(data_publicacao=date(2025, 12, 1), n_amostras=85, unidade="soja")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.amostral == Amostral.ABAIXO_DA_META
    assert av.cobertura_da_meta == pytest.approx(85 / 231)
    assert "231" in av.motivo and "85" in av.motivo, "o denominador fica à vista"
    assert "37%" in av.motivo


def test_a_palavra_insuficiente_nao_aparece_em_lugar_nenhum():
    """Trava de redação. "Insuficiente" é afirmação sobre representatividade no
    país; exigiria população-alvo, desenho probabilístico, perdas e desfecho —
    nada disso publicado, nada disso recalculado por nós."""
    obs = Observacao(data_publicacao=date(2025, 12, 1), n_amostras=85, unidade="soja")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert "insuficiente" not in av.motivo.lower()
    assert "insuficiente" not in av.amostral.lower()


def test_laranja_atinge_a_meta():
    obs = Observacao(data_publicacao=date(2025, 12, 1), n_amostras=240, unidade="laranja")
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert av.amostral == Amostral.ATINGE_A_META
    assert av.cobertura_da_meta > 1.0


def test_sem_meta_declarada_nao_avalia_amostra():
    """Não inventamos meta para quem não declarou uma."""
    obs = Observacao(data_publicacao=date(2026, 3, 1), n_amostras=3)
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE)
    assert av.amostral == Amostral.NAO_AVALIAVEL
    assert av.cobertura_da_meta is None


# ── granularidade ────────────────────────────────────────────────────────
def test_granularidade_ausente_nao_e_ausencia_de_dado():
    """O PARA recente não desagrega por UF. O dado existe — só não nesse nível.
    É falha de granularidade, com outro remédio."""
    obs = Observacao(data_publicacao=date(2025, 12, 1))
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE, eixo_pedido="uf")
    assert av.granularidade == Granularidade.NAO_DESAGREGAVEL
    assert av.temporal == Temporal.NO_PRAZO, "continua em dia; o que falta é o recorte"


def test_ibama_desagrega_por_uf():
    obs = Observacao(data_publicacao=date(2026, 3, 1))
    av = latencia.avaliar(fontes.IBAMA_COMERCIALIZACAO, obs, HOJE, eixo_pedido="uf")
    assert av.granularidade == Granularidade.DISPONIVEL


# ── grau de confiança ────────────────────────────────────────────────────
def test_regua_lida_no_primario_mais_publicacao_observada_da_confianca_alta():
    """O PARA é a única fonte do catálogo com régua conferida no documento."""
    obs = Observacao(data_publicacao=date(2025, 12, 1))
    av = latencia.avaliar(fontes.ANVISA_PARA, obs, HOJE)
    assert fontes.ANVISA_PARA.regua_verificada
    assert av.confianca == Confianca.ALTA


def test_regua_por_verificar_sobre_data_inferida_da_confianca_baixa():
    """O pior caso do catálogo: régua não conferida no primário e data que veio do
    documento, não da observação. O painel precisa mostrar que essa cor pesa menos."""
    obs = Observacao(data_referencia=date(2018, 12, 31))
    av = latencia.avaliar(fontes.MAPA_PNCRC, obs, HOJE)
    assert not fontes.MAPA_PNCRC.regua_verificada
    assert av.base_temporal == Base.REFERENCIA
    assert av.confianca == Confianca.BAIXA


def test_um_ingrediente_bom_de_dois_da_moderada():
    obs = Observacao(data_publicacao=date(2018, 12, 31))
    av = latencia.avaliar(fontes.MAPA_PNCRC, obs, HOJE)
    assert av.confianca == Confianca.MODERADA


def test_ler_a_portaria_promoveu_a_confianca_do_sisagua():
    """Efeito concreto de uma tarde de leitura: a mesma observação que antes valia
    confiança BAIXA agora vale MODERADA, e vale ALTA assim que o registrador
    conseguir datar a publicação. Nada no dado mudou — mudou o que sabemos da régua."""
    ref = Observacao(data_referencia=date(2022, 12, 31))
    pub = Observacao(data_publicacao=date(2022, 12, 31))
    assert latencia.avaliar(fontes.MS_SISAGUA_AGROTOXICOS, ref, HOJE).confianca == Confianca.MODERADA
    assert latencia.avaliar(fontes.MS_SISAGUA_AGROTOXICOS, pub, HOJE).confianca == Confianca.ALTA


def test_sem_calendario_nao_tem_confianca_a_declarar():
    """Não há classificação temporal, logo não há o que graduar."""
    obs = Observacao(data_publicacao=date(2026, 9, 11))
    av = latencia.avaliar(fontes.ANVISA_MONOGRAFIAS, obs, HOJE)
    assert av.temporal == Temporal.SEM_CALENDARIO
    assert av.confianca == Confianca.NAO_CLASSIFICAVEL


def test_nada_localizado_tem_confianca_baixa():
    """Porque não se distingue "nunca mediram" de "mediram e não publicaram" de
    "publicaram onde não olhamos"."""
    av = latencia.avaliar(fontes.ANVISA_PARA, Observacao(), HOJE)
    assert av.confianca == Confianca.BAIXA


# ── higiene do catálogo ──────────────────────────────────────────────────
def test_ids_sao_unicos():
    ids = [f.id for f in fontes.CATALOGO]
    assert len(ids) == len(set(ids))


def test_toda_fonte_declara_a_origem_da_regua():
    """Régua sem procedência não sustenta afirmação pública. Este teste existe
    para impedir que alguém acrescente uma fonte com periodicidade inventada."""
    for f in fontes.CATALOGO:
        assert f.regua_fonte.strip(), "%s sem regua_fonte" % f.id
        if f.meta_amostral is not None:
            assert f.regua_meta, "%s declara meta sem dizer de onde vem" % f.id


def test_regua_nao_verificada_esta_sinalizada():
    """Parte do catálogo ainda não teve a régua conferida no documento primário.
    O teste não reprova por isso — registra quais faltam, para não esquecermos."""
    pendentes = [f.id for f in fontes.CATALOGO if not f.regua_verificada]
    assert set(pendentes) == {"mapa_pncrc"}, (
        "mudou a lista de réguas por verificar: %s" % pendentes)


def test_o_sisagua_e_semestral_e_nao_trimestral():
    """Lido no Anexo 13 do Anexo XX em 14/09/2026.

    O catálogo dizia 'trimestral obrigatório', vindo de reportagem, e estava
    errado. Agrotóxicos caem em 'Demais parâmetros': 1 amostra SEMESTRAL na saída
    do tratamento, superficial ou subterrâneo. O trimestre da nota (9) é regime de
    escalada após detecção — outra coisa.

    Este teste é a cicatriz: se alguém voltar a pôr 3 aqui, precisa passar por ele."""
    f = fontes.MS_SISAGUA_AGROTOXICOS
    assert f.periodicidade_meses == 6
    assert f.regua_verificada
    assert "Anexo 13" in f.regua_fonte
    assert "2.472" in f.regua_fonte, "a tabela em vigor não é a da 888/2021"


def test_regua_por_verificar_diz_o_que_falta_ler():
    """Não basta marcar `regua_verificada=False`. Um False mudo vira dívida
    esquecida; um False que nomeia o documento vira tarefa. Tentativa frustrada é
    resultado, e fica registrada — inclusive para que ninguém a repita à toa."""
    for f in fontes.CATALOGO:
        if f.regua_verificada:
            continue
        assert f.observacao.strip(), "%s sem registro do que falta" % f.id
        assert "14/09/2026" in f.observacao, (
            "%s precisa datar a tentativa de verificação" % f.id)


def test_o_pncrc_separa_promessa_de_medir_de_promessa_de_publicar():
    """A distinção que o módulo inteiro passou a fazer, aplicada ao catálogo.

    Plano anual de amostragem é compromisso de MEDIR. Não se achou compromisso de
    PUBLICAR. Usar um para cobrar o outro é comparar coisas diferentes — e era
    exatamente o erro que a separação de datas veio impedir."""
    f = fontes.MAPA_PNCRC
    assert "MEDIR, não de" in f.regua_fonte
    assert "publicar" in f.regua_fonte.lower()


def test_o_ibama_e_anual_desde_2021_e_nao_semestral():
    """Lido no art. 41 consolidado em 14/09/2026.

    O Decreto 10.833/2021 trocou 'até 31 de janeiro e 31 de julho' por
    'anualmente, até 31 de janeiro' — afrouxamento de semestral para anual. O
    catálogo dizia seis meses, seguindo a página do IBAMA, e estava errado.

    Segunda cicatriz do mesmo tipo da do SISAGUA: as duas réguas que vinham de
    página institucional ou de reportagem estavam erradas, e as duas erravam para
    o lado de cobrar mais do que a norma exige."""
    f = fontes.IBAMA_COMERCIALIZACAO
    assert f.periodicidade_meses == 12
    assert f.regua_verificada
    assert "10.833" in f.regua_fonte


def test_o_ibama_publica_menos_granular_do_que_o_decreto_manda_coletar():
    """O achado mais limpo do catálogo, porque não depende de juízo nosso.

    O § 2º do art. 41 exige quantitativos MENSAIS das empresas. O CSV publicado
    traz colunas SEMESTRE e ANO. O dado nasce mensal e chega ao público agregado
    por semestre — perda de granularidade entre o que o governo recebe e o que
    publica, medida contra a régua do próprio órgão."""
    f = fontes.IBAMA_COMERCIALIZACAO
    assert "MENSAIS" in f.regua_fonte, "a exigência mensal precisa estar na régua"
    assert f.desagrega_por("semestre"), "é o que o CSV de fato entrega"
    assert not f.desagrega_por("mes"), (
        "se um dia o IBAMA publicar o mês, este teste falha — e falhar aqui é a "
        "notícia: a lacuna que o instrumento aponta terá sido fechada")


def test_a_pagina_do_ibama_contradiz_o_decreto_e_isso_fica_registrado():
    """A fonte contradiz a si mesma: o site anuncia 'Relatório Semestral' com
    prazos de 31/01 e 31/07, que é a redação anterior. Quem confia no site cobra
    prazo inexistente; quem confia no decreto não acha isso dito no site.

    Foi previsto antes de saber a resposta, e é o tipo de falha que o instrumento
    existe para tornar visível."""
    o = fontes.IBAMA_COMERCIALIZACAO.observacao
    assert "página" in o.lower() and "anterior" in o.lower()


def test_o_catalogo_registra_que_trimestre_significa_deteccao():
    """A inversão de leitura que a nota (9) impõe. Sem isso registrado, alguém
    lerá 'mede trimestralmente' como bom desempenho, quando é o oposto."""
    o = fontes.MS_SISAGUA_AGROTOXICOS.observacao
    assert "detectado" in o and "escalada" in o.lower()
    assert "art. 44" in o.lower(), "quem mede é o responsável pelo SAA, não o MS"


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
