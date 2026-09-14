# -*- coding: utf-8 -*-
"""
Testes do registrador.

Nenhum toca a rede. O que se testa aqui é a INTERPRETAÇÃO do que o servidor
respondeu, não a capacidade de falar com ele — e é a interpretação que decide se
uma mudança vira notícia ou passa batida.

A separação entre `consultar` (fala com a rede) e `divergencias` (julga o que
voltou) existe justamente para isso.
"""
import io
import os
from datetime import datetime, timezone

import pytest

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro import registrador as reg

AGORA = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def registro(**kw):
    base = dict(carimbo=AGORA.isoformat(timespec="seconds"),
                fonte_id="anvisa_para", url="http://exemplo", metodo="HEAD",
                http_status=200, content_type="application/pdf",
                content_length=853188, last_modified="", etag="", erro="")
    base.update(kw)
    return reg.Registro(**base)


# ── o que faz uma observação virar notícia ───────────────────────────────
def test_formato_conforme_o_catalogo_nao_gera_divergencia():
    assert reg.divergencias(cat.ANVISA_PARA, registro()) == ()


def test_mudanca_de_formato_em_fonte_com_endpoint_e_noticia():
    """Se uma fonte com endereço estável trocar de formato, o instrumento avisa."""
    d = reg.divergencias(cat.IBAMA_COMERCIALIZACAO,
                         registro(fonte_id="ibama_comercializacao",
                                  content_type="application/pdf"))
    assert d, "mudança de formato não pode passar batida"
    assert "CSV" in d[0] and "application/pdf" in d[0]


def test_ponto_cego_conhecido_fonte_so_com_pagina():
    """LIMITE DO REGISTRADOR, documentado de propósito.

    O desfecho que este projeto persegue é a Anvisa passar a publicar o PARA em
    formato aberto. O registrador NÃO detectaria isso sozinho: ele consulta a
    página de relatórios, que continuará devolvendo text/html mesmo que um CSV
    novo apareça listado dentro dela.

    Detectar exigiria varrer o HTML atrás de links para arquivo — o que traz
    fragilidade a mudança de layout e fica para depois, se valer a pena. Por
    enquanto, a descoberta é humana, e o catálogo é atualizado à mão.

    Este teste existe para que o ponto cego seja uma decisão registrada, e não
    uma surpresa para quem confiar no instrumento."""
    r = registro(fonte_id="anvisa_para", content_type="text/html")
    assert reg.divergencias(cat.ANVISA_PARA, r) == (), (
        "hoje, por desenho, uma fonte só-com-página nunca diverge por formato")


def test_octet_stream_nao_prova_nada():
    """É o que o servidor responde quando não sabe dizer. O IBAMA serve o CSV
    assim. Tratar como divergência encheria o registro de falso positivo."""
    assert reg.divergencias(cat.IBAMA_COMERCIALIZACAO,
                            registro(fonte_id="ibama_comercializacao",
                                     content_type="application/octet-stream")) == ()


def test_fonte_fora_do_ar_e_observacao_e_nao_erro():
    d = reg.divergencias(cat.ANVISA_PARA, registro(http_status=None, erro="timeout"))
    assert d and "inacessível" in d[0]


def test_404_vira_divergencia():
    d = reg.divergencias(cat.ANVISA_PARA, registro(http_status=404, content_type=""))
    assert d == ("HTTP 404",)


def test_duzentos_com_corpo_vazio_e_achado():
    """Responder 200 sem conteúdo é pior que responder erro: parece que está lá."""
    d = reg.divergencias(cat.ANVISA_PARA, registro(content_length=0))
    assert any("vazio" in x for x in d)


def test_respondeu_so_para_2xx():
    assert registro(http_status=200).respondeu
    assert registro(http_status=206).respondeu          # GET com Range
    assert not registro(http_status=302).respondeu
    assert not registro(http_status=None).respondeu


# ── persistência ─────────────────────────────────────────────────────────
def test_primeira_escrita_cria_cabecalho(tmp_path):
    alvo = str(tmp_path / "sub" / "registro.csv")
    reg.acrescentar([registro()], alvo)
    linhas = io.open(alvo, encoding="utf-8").read().splitlines()
    assert linhas[0] == ",".join(reg.COLUNAS)
    assert len(linhas) == 2


def test_segunda_rodada_anexa_sem_repetir_cabecalho(tmp_path):
    """O arquivo é append-only: cada rodada acrescenta, nunca reescreve. É o que
    torna o histórico de commits evidência de medição contínua."""
    alvo = str(tmp_path / "registro.csv")
    reg.acrescentar([registro()], alvo)
    reg.acrescentar([registro(carimbo="2026-10-14T12:00:00+00:00")], alvo)
    linhas = io.open(alvo, encoding="utf-8").read().splitlines()
    assert len(linhas) == 3
    assert linhas.count(",".join(reg.COLUNAS)) == 1


def test_terminador_de_linha_e_sempre_lf(tmp_path):
    """O arquivo é commitado e o CI roda em Linux. Sem isso, a mesma rodada no
    Windows e no CI produziria diffs diferentes."""
    alvo = str(tmp_path / "registro.csv")
    reg.acrescentar([registro()], alvo)
    bruto = io.open(alvo, "rb").read()
    assert b"\r\n" not in bruto


def test_none_vira_campo_vazio_e_nao_a_palavra_none(tmp_path):
    alvo = str(tmp_path / "registro.csv")
    reg.acrescentar([registro(http_status=None, content_length=None)], alvo)
    corpo = io.open(alvo, encoding="utf-8").read().splitlines()[1]
    assert "None" not in corpo


# ── etag ─────────────────────────────────────────────────────────────────
def test_etag_e_lido_e_vem_sem_aspas():
    """Servidores devolvem o etag entre aspas, às vezes com prefixo W/. Guardar
    com as aspas faria a mesma versão parecer duas ao comparar entre rodadas."""
    class FalsaResposta:
        status = 200
        headers = {"Content-Type": "text/csv", "Content-Length": "10",
                   "ETag": '"0x8DD1234ABCD"'}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import urllib.request
    original = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: FalsaResposta()
    try:
        r = reg.observar(cat.IBAMA_COMERCIALIZACAO, AGORA)
    finally:
        urllib.request.urlopen = original
    assert r.etag == "0x8DD1234ABCD"


def test_etag_ausente_vira_string_vazia_e_nao_quebra():
    """Nem todo servidor oferece. Ausência é o caso comum, não erro."""
    assert registro().etag == ""


def test_etag_vai_para_o_csv(tmp_path):
    alvo = str(tmp_path / "registro.csv")
    reg.acrescentar([registro(etag="abc123")], alvo)
    texto = io.open(alvo, encoding="utf-8").read()
    assert "etag" in texto.splitlines()[0]
    assert "abc123" in texto


# ── higiene ──────────────────────────────────────────────────────────────
def test_colunas_batem_com_o_dataclass():
    assert set(reg.COLUNAS) == set(reg.Registro.__dataclass_fields__)


def test_o_registro_do_ponto_zero_tem_a_coluna_nova():
    """A coluna `etag` entrou depois da primeira rodada. O arquivo é append-only,
    então foi preciso reescrever cabeçalho e completar as linhas antigas com campo
    vazio — preservando as cinco observações de 14/09/2026. Este teste garante que
    a migração não deixou o arquivo incoerente com o código."""
    import csv, os
    alvo = os.path.join(os.path.dirname(__file__), "..", "dados", "registro_fontes.csv")
    if not os.path.exists(alvo):
        pytest.skip("registro ainda não existe neste checkout")
    linhas = list(csv.DictReader(io.open(alvo, encoding="utf-8")))
    assert linhas, "o ponto zero da série não pode ter sido perdido"
    for linha in linhas:
        assert set(linha) == set(reg.COLUNAS)


def test_todo_formato_do_catalogo_tem_content_type_esperado():
    """Fonte nova com formato sem mapeamento passaria a nunca divergir, o que é
    pior que divergir demais: falha em silêncio."""
    for f in cat.CATALOGO:
        assert f.formato in reg.ESPERADO, "%s usa formato sem mapeamento" % f.id


def test_agente_identifica_o_projeto():
    """Bater repetidamente em servidor público sem se identificar é má prática."""
    assert "painel-san" in reg.AGENTE and "github.com" in reg.AGENTE


@pytest.mark.parametrize("fonte", cat.CATALOGO, ids=[f.id for f in cat.CATALOGO])
def test_toda_fonte_tem_url_absoluta(fonte):
    assert fonte.url.startswith("https://"), fonte.id


# ── fontes sem endpoint estável ──────────────────────────────────────────
def test_pagina_respondendo_html_nao_e_divergencia():
    """Achado da primeira rodada, em 14/09/2026: três das cinco fontes não têm
    endereço estável que entregue o arquivo — a URL é a página onde ele mora.

    Cobrar delas um content-type de arquivo produziria divergência em toda
    rodada, para sempre, afogando as mudanças reais. A ausência de endpoint é
    achado permanente, registrado no catálogo, não notícia mensal."""
    r = registro(fonte_id="anvisa_para", content_type="text/html")
    assert not cat.ANVISA_PARA.endpoint_estavel
    assert reg.divergencias(cat.ANVISA_PARA, r) == ()


def test_fonte_com_endpoint_continua_sendo_cobrada():
    """A dispensa vale só para quem não tem endpoint. O IBAMA tem, e se ele
    passar a devolver HTML é porque algo quebrou."""
    r = registro(fonte_id="ibama_comercializacao", content_type="text/html")
    assert cat.IBAMA_COMERCIALIZACAO.endpoint_estavel
    assert reg.divergencias(cat.IBAMA_COMERCIALIZACAO, r)


def test_pagina_fora_do_ar_ainda_e_divergencia():
    """Não ter endpoint não dispensa a página de existir."""
    r = registro(fonte_id="anvisa_para", http_status=500, content_type="")
    assert reg.divergencias(cat.ANVISA_PARA, r) == ("HTTP 500",)


def test_quais_fontes_nao_tem_endpoint():
    """Trava a lista. Se uma delas passar a publicar endereço estável, este teste
    falha — e falhar aqui é a notícia."""
    sem = {f.id for f in cat.CATALOGO if not f.endpoint_estavel}
    assert sem == {"anvisa_para", "ms_sisagua_agrotoxicos", "mapa_pncrc"}
