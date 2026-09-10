# -*- coding: utf-8 -*-
"""
Testes da classificação NOVA.

Cada caso em CASOS_CONHECIDOS é um defeito que existiu de verdade no pipeline, ou
uma âncora que impede a correção de regredir. Os cinco primeiros viveram meses sem
produzir erro nenhum — nenhuma exceção, nenhum valor faltando, nenhuma linha a menos.
É esse o tipo de defeito que só teste pega.

Roda sem os 1,9 GB de microdados: a fixture traz só os nomes das 391 categorias.
"""
import io
import os
import re

import pytest

from painel_san.modulos.san import nova

AQUI = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(AQUI, "fixtures", "categorias_pof_2393.txt")


@pytest.fixture(scope="module")
def categorias():
    with io.open(FIXTURE, encoding="utf-8") as fh:
        return [l.strip() for l in fh if l.strip() and not l.startswith("#")]


@pytest.fixture(scope="module")
def folhas(categorias):
    """Só produtos folha entram no cálculo de participação calórica."""
    return [c for c in categorias if nova.is_produto_folha(c)]


# ── defeitos reais, fixados como casos ───────────────────────────────────
CASOS_CONHECIDOS = [
    # A regra generica ["sal"] casava por substring dentro de "salgado" e mandava
    # estes para NOVA 2 com kcal=0, o que os removia do calculo em silencio.
    ("16.1.8 Salgadinho",              4, "ultraprocessado de manual"),
    ("6.3.3 Biscoito salgado",         4, "biscoito"),
    ("9.1 Pescados de água salgada",   1, "pescado, nao ingrediente culinario"),
    # Sinonimos escritos como lista viram AND e nunca disparam. Estes quatro caiam
    # no fallback do grupo, no grupo errado.
    ("6.3.1 Biscoito doce",            4, "todo biscoito e NOVA 4"),
    ("15.1.1 Aguardente de cana",      3, "destilado, nao alimento in natura"),
    ("12.2.6 Doce de fruta em pasta",  3, "goiabada = fruta + acucar"),
    ("12.2.3 Doce a base de leite",    3, "leite + acucar; NOVA 4 exigiria aditivo"),
    # Ancoras: o casamento por substring nao pode capturar estes por engano.
    ("13.1.2 Sal refinado",            2, "sal de verdade"),
    ("3.1.20 Melancia",                1, "'mel' esta dentro de 'melancia'"),
    ("5.3.1 Macarrão com ovos",        1, "'maca' esta dentro de 'macarrao'"),
    ("7.5.8 Salsicha comum",           4, "'cha' esta dentro de 'salsicha'"),
    ("2.2.12 Tomate",                  1, "'mate' esta dentro de 'tomate'"),
    ("1.1.2 Arroz polido",             1, "'po' esta dentro de 'polido'"),
]


@pytest.mark.parametrize("produto,esperado,porque",
                         CASOS_CONHECIDOS,
                         ids=[c[0].split(" ", 1)[-1][:26] for c in CASOS_CONHECIDOS])
def test_classificacao_conhecida(produto, esperado, porque):
    grupo, _ = nova.classificar_produto(produto)
    assert grupo == esperado, "%s caiu em NOVA %s (%s)" % (produto, grupo, porque)


# ── invariantes ──────────────────────────────────────────────────────────
SEM_ENERGIA = re.compile(r"(^|[^a-z])(sal|vinagre|agua|adocante|cha|cafe)([^a-z]|$)")


def test_kcal_zero_so_para_condimento(folhas):
    """kcal=0 nao classifica errado: remove o item do numerador E do denominador,
    ou seja, faz o alimento sumir do calculo sem erro nenhum. Foi assim que o
    defeito do "sal" passou meses despercebido."""
    culpados = []
    for c in folhas:
        grupo, kcal = nova.classificar_produto(c)
        if kcal == 0 and not SEM_ENERGIA.search(nova.normalizar(c)):
            culpados.append(c)
    assert not culpados, "alimentos com kcal=0 somem do calculo: %s" % culpados


def test_todo_produto_folha_recebe_classificacao(folhas):
    orfaos = [c for c in folhas if nova.classificar_produto(c)[0] is None]
    assert not orfaos, "sem classificacao: %s" % orfaos[:10]


def test_grupos_sao_validos(folhas):
    for c in folhas:
        grupo, kcal = nova.classificar_produto(c)
        assert grupo in (1, 2, 3, 4), "%s -> grupo %r" % (c, grupo)
        assert 0 <= kcal <= 950, "%s -> %r kcal" % (c, kcal)


def test_modulo_e_puro():
    """A camada de classificacao nao pode depender de UI nem de I/O.

    Rodado num processo LIMPO de proposito. Checar sys.modules dentro da suite nao
    serve: o pytest ja importou pandas por causa de test_ingestao.py, e como os
    arquivos rodam em ordem alfabetica o resultado dependeria de qual teste veio
    antes. O subprocesso importa so o nova e mais nada."""
    import subprocess
    import sys
    codigo = (
        "import sys;"
        "import painel_san.modulos.san.nova;"
        "proibidos=[m for m in ('streamlit','pandas','numpy') if m in sys.modules];"
        "print(proibidos);"
        "sys.exit(1 if proibidos else 0)"
    )
    r = subprocess.run([sys.executable, "-c", codigo],
                       capture_output=True, text=True)
    assert r.returncode == 0, "nova.py arrastou dependencia pesada: %s" % r.stdout.strip()


# ── higiene das regras ───────────────────────────────────────────────────
def _chaves(kws):
    return kws if isinstance(kws, list) else [kws]


def _dispara(kws, categorias):
    ks = [nova.normalizar(w) for w in _chaves(kws)]
    return any(all(k in nova.normalizar(c) for k in ks) for c in categorias)


def _grupo_real(kws, folhas):
    """Se as chaves fossem OR, que produtos elas pegariam — e em que grupo esses
    produtos caem hoje?"""
    ks = [nova.normalizar(w) for w in _chaves(kws)]
    for c in folhas:
        cn = nova.normalizar(c)
        if any(k in cn for k in ks):
            yield c, nova.classificar_produto(c)[0]


# Regras que nunca disparam e cuja divergencia foi AVALIADA e aceita em
# 10/09/2026. Duas razoes distintas convivem aqui:
#
#   1. Conjuncao deliberada. ["leite", "achocolatado"] quer dizer "leite
#      achocolatado", e nenhuma categoria da POF se chama assim. Interpretar como
#      OR seria pior, nao melhor: faria leite de vaca fresco virar NOVA 4. Idem
#      ["cafe", "nao especificado"], que em OR pegaria "Biscoito nao especificado",
#      e ["frango", "galinha", ...], que pegaria "Caldo de galinha em tablete" —
#      um ultraprocessado — e o classificaria como carne fresca. Estas regras
#      estao mortas E ISSO ESTA CERTO.
#
#   2. Sinonimo morto cujo fallback de grupo da o mesmo grupo NOVA. So a densidade
#      calorica difere, e o efeito foi medido: no maior caso, coco-da-baia,
#      0,055% do denominador.
DIVERGENCIA_ACEITA = {
    "['alcatra', 'patinho', 'filé mignon', 'contrafilé', 'lagarto', 'acém', "
    "'músculo', 'capa de filé', 'chã-de-dentro', 'peito bovino']",
    "['frango', 'galinha', 'peru', 'pato', 'aves']",
    "['tilápia', 'tilapia', 'sardinha fresca', 'parati', 'tucunaré', 'tambaqui', 'lambari']",
    "['coco-da-baía', 'coco da baia']",
    "['cheiro-verde', 'cheiro verde']",
    "['nugget', 'empanado']",
    "['pipoca', 'industrializ']",
    "['refeição pronta', 'refeição']",
    "['carne', 'bovina', 'não especificada']",
    "['café', 'não especificado']",
    "['leite', 'achocolatado']",
    "['achocolatado', 'pó']",
    "['outras', 'bebidas alcoólicas']",
    "['castanha', 'nozes', 'amendoim', 'amêndoa', 'amendoas']",
}


def test_nenhuma_regra_morta_com_dano(categorias, folhas):
    """O defeito que custou caro nao e "regra que nao dispara" — e regra que nao
    dispara E cujos produtos caem no GRUPO ERRADO por causa disso.

    Uma regra para "ketchup" que nao acha ketchup na POF e inofensiva: a POF nao
    itemiza ketchup. Mas ["biscoito", "bolacha"] escrita junta exigia as duas
    palavras no mesmo nome, nunca disparava, e mandava todos os biscoitos para
    NOVA 3 pelo fallback do grupo. Foi assim com biscoito, aguardente, goiabada
    e doce de leite, e custou tres passadas de correcao em quatro artefatos.

    Reprova enquanto o caso nao for avaliado e, se aceitavel, anotado acima."""
    danos = []
    for lista in ("REGRAS_NOVA4", "REGRAS_NOVA3", "REGRAS_NOVA2", "REGRAS_NOVA1"):
        for kws, grupo, kcal in getattr(nova, lista):
            if _dispara(kws, categorias):
                continue
            if str(kws) in DIVERGENCIA_ACEITA:
                continue
            for produto, real in _grupo_real(kws, folhas):
                if real != grupo:
                    danos.append((str(kws), "pretendia NOVA %s" % grupo,
                                  produto, "caiu em NOVA %s" % real))
                    break
    assert not danos, "regras mortas mandando produto para o grupo errado: %s" % danos
