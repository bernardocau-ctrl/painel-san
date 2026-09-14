# -*- coding: utf-8 -*-
"""
Testes do conector do PARA.

Nenhum abre o PDF. O relatório tem 2,8 MB e não está no repositório — o que se
testa aqui é a INTERPRETAÇÃO do texto, com trechos que reproduzem as armadilhas
reais, mais a coerência da tabela curada que está versionada.

O único teste que toca o PDF pula sozinho quando ele não está presente.
"""
import io
import os

import pytest

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro import latencia as lat
from painel_san.modulos.alimento_seguro import para

from datetime import date

HOJE = date(2026, 9, 14)
CSV = os.path.join(os.path.dirname(__file__), "..", "dados", "para_2024.csv")


# ── as duas armadilhas do PDF ────────────────────────────────────────────
def test_o_sumario_nao_pode_capturar_a_extracao():
    """ARMADILHA 1. O sumário repete os títulos das seções. Buscar a primeira
    ocorrência de "n. Cebola" acha o índice, que não tem número nenhum — e o
    alimento sairia vazio, em silêncio."""
    texto = ("SUMÁRIO a. Cebola .......... 88 "
             "CORPO a. Cebola Foram analisadas 238 amostras de cebola. "
             "31 amostras foram consideradas insatisfatórias.")
    res, faltaram = para.extrair(texto, 2024)
    assert "Cebola" not in faltaram
    cebola = [r for r in res if r.alimento == "Cebola"]
    assert cebola and cebola[0].n_amostras == 238
    assert cebola[0].n_insatisfatorias == 31


def test_digito_quebrado_pelo_pdf_e_remontado():
    """A causa da armadilha 2, e a evidência mais concreta de que o PARA não é
    dado aberto: o PDF parte números entre trechos de texto. A banana aparece
    como "22 2 amostras" e o trigo como "2 34". Um arquivo em que 234 não está
    escrito como 234 não é legível por máquina, por mais que caiba num PDF."""
    texto = ("a. Trigo Foram analisadas 2 34 amostras de farinha de trigo. "
             "Cinco amostras foram consideradas insatisfatórias.")
    res, _ = para.extrair(texto, 2024)
    assert res[0].n_amostras == 234


def test_numero_composto_por_extenso_e_ponto_cego_conhecido():
    """LIMITE DA EXTRAÇÃO, documentado de propósito.

    "Trinta e uma amostras" devolveria 1, não 31, porque só o último token é lido.
    Não morde no ciclo 2024 — a validação contra os dois totais publicados prova
    isso, e os valores acima de vinte vêm em dígitos no relatório. Mas morderia em
    silêncio num ciclo futuro, e a validação pegaria o erro sem explicar a causa.

    Fica registrado para que, quando a soma não fechar em 2025, alguém saiba onde
    olhar primeiro."""
    assert para.valor("uma") == 1
    texto = ("a. Cebola Foram analisadas 238 amostras. "
             "Trinta e uma amostras foram consideradas insatisfatórias.")
    res, _ = para.extrair(texto, 2024)
    assert res[0].n_insatisfatorias == 1, (
        "ponto cego conhecido: composto por extenso lê só o último token")


def test_numero_por_extenso_e_lido():
    """O relatório escreve pequenos números por extenso. Sem isto, os alimentos
    MENOS irregulares sairiam vazios — e sumiriam justamente os casos que servem
    de contraste no painel."""
    texto = ("a. Trigo Foram analisadas 234 amostras de trigo. "
             "Cinco amostras foram consideradas insatisfatórias.")
    res, _ = para.extrair(texto, 2024)
    assert res[0].n_insatisfatorias == 5


def test_nenhuma_conta_como_zero_e_nao_como_ausencia():
    """Alimento sem nenhuma irregularidade é resultado, não falha de extração."""
    assert para.valor("nenhuma") == 0
    assert para.valor("Nenhuma") == 0


def test_valor_recusa_o_que_nao_e_numero():
    assert para.valor("abacaxi") is None
    assert para.valor("1.234") == 1234


def test_cabecalho_de_pagina_nao_quebra_a_frase():
    """O cabeçalho se repete em toda página e cai no meio das frases."""
    sujo = ("a. Uva Foram analisadas 234 amostras Anvisa – Agência Nacional de "
            "Vigilância Sanitária Página 77 de 150 de uva. Sessenta e seis ...")
    assert "Página" not in para.limpar(sujo)


# ── a validação é o que autoriza gravar ──────────────────────────────────
def test_validacao_recusa_soma_que_nao_fecha():
    """Sem isto o módulo repousaria sobre expressões regulares aplicadas a um PDF
    que muda de diagramação sem avisar."""
    res = (para.Resultado(2024, "Soja", 85, 7),)
    ok, msg = para.valida(res, 2024, faltaram=())
    assert not ok
    assert "somei" in msg or "extraí" in msg


def test_validacao_recusa_alimento_faltando():
    ok, msg = para.valida((), 2024, faltaram=("Cebola",))
    assert not ok and "Cebola" in msg


def test_validacao_recusa_ciclo_sem_totais_publicados():
    """Ciclo novo sem os dois totais registrados não pode ser validado — e sem
    validação não se grava. É o que impede alguém de ingerir 2025 no escuro."""
    ok, msg = para.valida((), 2027, faltaram=())
    assert not ok and "2027" in msg


def test_a_tabela_curada_bate_com_os_totais_publicados():
    """O teste central do conector: o que está versionado reproduz os dois números
    que a Anvisa publica no corpo do relatório — 3.084 amostras e 20,6%."""
    res = para.ler_csv(CSV)
    ok, msg = para.valida(res, 2024, faltaram=())
    assert ok, msg
    assert sum(r.n_amostras for r in res) == 3084


def test_a_soja_e_o_pior_caso_de_cobertura():
    """85 de 231. Registrado como número, não como adjetivo."""
    res = {r.alimento: r for r in para.ler_csv(CSV)}
    assert res["Soja"].n_amostras == 85
    assert res["Soja"].n_amostras / cat.ANVISA_PARA.meta_amostral < 0.4


def test_o_trigo_veio_da_prosa_e_nao_da_tabela():
    """ARMADILHA 2, travada em teste. A Tabela 3 do relatório traz trigo com 224;
    a prosa diz 234, e só com 234 a soma fecha nos 3.084 publicados. Se alguém
    trocar a extração para ler tabelas, este teste cai junto com a validação."""
    res = {r.alimento: r for r in para.ler_csv(CSV)}
    assert res["Trigo"].n_amostras == 234, "224 é o valor errado, o da Tabela 3"


# ── estatística ──────────────────────────────────────────────────────────
def test_wilson_nao_escapa_para_baixo_de_zero():
    """Com n pequeno e p perto de zero o intervalo normal simples fica negativo.
    O trigo, 5 em 234, é exatamente esse caso."""
    lo, hi = para.wilson(5, 234)
    assert lo >= 0.0 and lo < hi < 100.0


def test_wilson_com_n_zero_nao_levanta():
    assert para.wilson(0, 0) == (0.0, 0.0)


def test_distinguiveis_contem_a_leitura_do_painel():
    """"O pepino tem mais resíduo que o trigo" é afirmação que a amostragem
    sustenta. "A maçã tem mais que a uva" não é — e numa barra ordenada as duas
    pareceriam igualmente verdadeiras."""
    r = {x.alimento: x for x in para.ler_csv(CSV)}
    assert para.distinguiveis(r["Pepino"], r["Trigo"])
    assert not para.distinguiveis(r["Maçã"], r["Uva"])


# ── a ponte com a avaliação ──────────────────────────────────────────────
def test_avalia_os_36_do_plano_e_nao_os_14_medidos():
    """A diferença é o módulo inteiro: percorrer os medidos mostra o que existe;
    percorrer o plano mostra o que falta, que é o objeto."""
    avs = para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)
    assert len(avs) == 36 == len(cat.PARA_CRONOGRAMA)


def test_os_quatro_desfechos_aparecem():
    avs = para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)
    estados = {a.temporal for a in avs}
    assert lat.Temporal.NO_PRAZO in estados
    assert lat.Temporal.AUSENCIA_PLANEJADA in estados
    assert lat.Temporal.NAO_APURADO in estados


def test_pendencia_nossa_nao_alerta_contra_a_anvisa():
    """O defeito que o resultado real expôs, travado como teste.

    Com só o ciclo 2024 extraído, doze dos trinta e seis alimentos acendiam como
    lacuna da Anvisa — quando a lacuna era a nossa lista de tarefas. Um painel
    assim diria o contrário do verdadeiro, e cairia diante de quem tivesse lido o
    relatório de 2023."""
    avs = para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)
    nossas = [a for a in avs if a.pendencias_nossas]
    assert nossas, "os alimentos de 2023 são pendência nossa"
    for a in nossas:
        assert not a.tem_alerta, "%s acusa a Anvisa por trabalho nosso" % a.unidade
        assert a.confianca == lat.Confianca.NAO_CLASSIFICAVEL
        assert "pendência nossa" in a.motivo


def test_os_alertas_reais_sao_so_os_seis_abaixo_da_meta():
    """Os seis que o próprio relatório documenta. Nenhum a mais."""
    avs = para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)
    com_alerta = sorted(a.unidade for a in avs if a.tem_alerta)
    assert com_alerta == ["abobrinha", "banana", "couve", "mamao", "pepino", "soja"]


def test_ciclo_ingerido_com_alimento_ausente_e_achado_de_verdade():
    """A distinção que dá sentido à anterior: se lemos o relatório do ciclo em que
    o alimento deveria estar e ele não estava, aí sim é lacuna do órgão."""
    cronograma = {"fantasma": (2024,)}
    obs = para.observacoes((para.Resultado(2024, "Cebola", 238, 31),), 2024, cronograma)
    assert len(obs) == 1 and not obs[0].nao_apurado, (
        "o ciclo 2024 foi ingerido; a ausência do alimento nele é achado")
    av = lat.avaliar(cat.ANVISA_PARA, obs[0], HOJE)
    assert av.temporal == lat.Temporal.NADA_LOCALIZADO
    assert av.tem_alerta


def test_morango_continua_sendo_ausencia_planejada():
    """O caso que abriu o módulo, agora com dado real ao redor."""
    avs = {a.unidade: a for a in para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)}
    assert avs["morango"].temporal == lat.Temporal.AUSENCIA_PLANEJADA
    assert not avs["morango"].tem_alerta


def test_a_cobertura_da_meta_chega_avaliada():
    avs = {a.unidade: a for a in para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)}
    assert avs["soja"].cobertura_da_meta == pytest.approx(85 / 231)
    assert avs["soja"].amostral == lat.Amostral.ABAIXO_DA_META
    assert avs["laranja"].amostral == lat.Amostral.ATINGE_A_META


def test_a_data_e_de_referencia_e_nao_de_publicacao():
    """Do PDF se extrai a que ciclo o dado se refere, nunca quando ele foi
    publicado. A avaliação precisa registrar essa diferença, não apagá-la."""
    avs = {a.unidade: a for a in para.avaliar_ciclo(para.ler_csv(CSV), 2024, HOJE)}
    assert avs["soja"].base_temporal == lat.Base.REFERENCIA
    assert "publicação desconhecida" in avs["soja"].motivo


# ── acentuação ───────────────────────────────────────────────────────────
def test_chave_liga_o_relatorio_ao_cronograma():
    """O relatório escreve "Maçã", o Plano Plurianual escreve "maca". Sem a
    junção, o alimento não encontraria o próprio cronograma."""
    assert para.chave("Maçã") == "maca"
    assert para.chave("Mamão") == "mamao"
    assert para.chave(" CEBOLA ") == "cebola"


def test_todo_alimento_do_ciclo_existe_no_cronograma():
    """Se um nome divergir, o alimento vira lacuna inexistente — falha silenciosa
    exatamente do tipo que este projeto já pagou caro para aprender."""
    faltam = [a for a in para.ALIMENTOS[2024]
              if para.chave(a) not in {para.chave(k) for k in cat.PARA_CRONOGRAMA}]
    assert not faltam, "fora do cronograma: %s" % faltam


# ── persistência ─────────────────────────────────────────────────────────
def test_ida_e_volta_do_csv(tmp_path):
    alvo = str(tmp_path / "p.csv")
    res = (para.Resultado(2024, "Soja", 85, 7), para.Resultado(2024, "Maçã", 235, 63))
    para.gravar(res, alvo)
    assert set(para.ler_csv(alvo)) == set(res)


def test_terminador_de_linha_e_sempre_lf(tmp_path):
    """O arquivo é commitado e o CI roda em Linux."""
    alvo = str(tmp_path / "p.csv")
    para.gravar((para.Resultado(2024, "Soja", 85, 7),), alvo)
    assert b"\r\n" not in io.open(alvo, "rb").read()


def test_o_csv_versionado_tem_as_colunas_do_dataclass():
    linhas = io.open(CSV, encoding="utf-8").read().splitlines()
    assert linhas[0] == ",".join(para.COLUNAS)
    assert len(linhas) == 15, "cabeçalho mais os catorze alimentos do ciclo"


# ── contra o PDF de verdade, quando ele estiver à mão ─────────────────────
def test_extracao_do_pdf_reproduz_a_tabela_curada():
    """Fecha a cadeia de evidência. Pula quando o PDF não está presente — ele não
    vai para o repositório, mas quem baixar da Anvisa pode conferir tudo."""
    pdf = os.path.join(os.path.dirname(__file__), "..", "..", "para2024.pdf")
    if not os.path.exists(pdf):
        pytest.skip("relatório do PARA não está neste checkout")
    res, faltaram = para.extrair(para.ler_pdf(pdf), 2024)
    ok, msg = para.valida(res, 2024, faltaram)
    assert ok, msg
    assert set(res) == set(para.ler_csv(CSV)), (
        "o PDF não reproduz a tabela versionada — alguém mexeu num dos dois")
