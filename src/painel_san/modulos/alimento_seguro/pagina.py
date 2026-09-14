# -*- coding: utf-8 -*-
"""
Mapa de frieza: a visualização em que a ausência é a figura, não o fundo.

A IDEIA, NA FRASE DE QUEM A TEVE
    "Temos um mapa de calor para monitorar dados em regiões, podemos sugerir um
    mapa de frieza."

    Um mapa de calor acende onde há muito dado. Este acende onde não há — e o
    desenho inteiro decorre disso: o que foi medido fica morno e discreto, o que
    falta fica frio e saliente. Quem bate o olho vê primeiro o vazio.

NÃO É UM MAPA DO BRASIL, E ISSO É PROPOSITAL
    A unidade aqui é o ALIMENTO, não o território. O PARA recente não desagrega
    por UF — está registrado no catálogo como falha de granularidade — e desenhar
    um coroplético com dado nacional seria inventar precisão territorial que a
    fonte não tem. A grade é o Plano Plurianual: trinta e seis alimentos, um por
    célula, do jeito que a Anvisa os planejou.

TRÊS BALDES, NUNCA SOMADOS
    lacuna da fonte    o órgão não entregou o que prometeu
    ausência planejada não devia haver dado agora; o plano marca para depois
    pendência nossa    NÓS ainda não fomos ver

    Somar os três daria um número maior e uma afirmação falsa. O terceiro existe
    porque um instrumento que mede a falta alheia precisa medir a própria com o
    mesmo rigor — sem ele, doze alimentos do ciclo 2023 apareceriam como culpa da
    Anvisa quando são a nossa lista de tarefas.

POR QUE A LÓGICA NÃO SABE DESENHAR
    `montar` e `resumo` não importam plotly nem streamlit: recebem avaliações e
    devolvem dados. `figura` desenha, `app` serve. A separação é o que torna o
    comportamento testável sem subir servidor — e é a crítica que mais derruba
    ferramenta web em revisão de software.
"""
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Sequence, Tuple

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro import latencia as lat


class Balde:
    """Em qual das três leituras a célula cai. Nunca somar."""
    LACUNA = "lacuna da fonte"
    EM_DIA = "medido, dentro da régua"
    PLANEJADA = "ausência planejada"
    NOSSA = "pendência nossa"

    ORDEM = (LACUNA, NOSSA, PLANEJADA, EM_DIA)


# Paleta do mapa de frieza. Frio e saliente onde falta; morno e discreto onde há.
#
# A escolha contraria o reflexo de pintar o problema de vermelho. Vermelho é a cor
# de alarme, e alarme é o que este instrumento não pode emitir: ele não afirma que
# o alimento está inseguro, afirma que o dado não permite saber. Azul profundo diz
# vazio, que é o que se está mostrando.
CORES = {
    Balde.LACUNA: "#1b4a6b",      # azul profundo — o vazio que o órgão deixou
    Balde.NOSSA: "#8a8f98",       # cinza — nossa dívida, visível e sem acusar
    Balde.PLANEJADA: "#dfe3e8",   # quase vazio — ausência legítima
    Balde.EM_DIA: "#c88a3d",      # âmbar contido — há dado aqui
}

SIMBOLOS = {
    # Cor sozinha não basta: parte dos leitores não a distingue, e o painel será
    # impresso em preto e branco em alguma banca.
    #
    # Quatro formas cheias, nenhuma "-open": no Plotly, símbolo aberto ignora a
    # cor de preenchimento e desenha só o contorno. Na primeira renderização as
    # doze pendências nossas saíram brancas sobre fundo branco — o maior grupo do
    # painel, invisível. Forma cheia é a única que honra a paleta.
    #
    # O par quadrado/losango separa os dois tipos de problema; o par
    # círculo/círculo pálido separa "há dado" de "ainda não devia haver".
    Balde.LACUNA: "square",
    Balde.NOSSA: "diamond",
    Balde.PLANEJADA: "circle",
    Balde.EM_DIA: "circle",
}

# Contorno por balde. A ausência planejada é a única que se apaga de propósito:
# ela não é falha de ninguém e não deve competir pelo olho.
CONTORNOS = {
    Balde.LACUNA: "#12354d",
    Balde.NOSSA: "#5f646b",
    Balde.PLANEJADA: "#c3c9d0",
    Balde.EM_DIA: "#9a6829",
}

COLUNAS_DA_GRADE = 6


@dataclass(frozen=True)
class Celula:
    """Um alimento do plano, e tudo o que sustenta sua cor.

    Carrega o cartão de evidência inteiro: quem quiser discordar da cor tem, na
    própria célula, a régua, sua origem, o motivo e o grau de confiança.
    """
    unidade: str
    balde: str
    estado: str
    confianca: str
    cobertura_da_meta: Optional[float]
    motivo: str
    regua: str
    regua_verificada: bool

    @property
    def cor(self) -> str:
        return CORES[self.balde]

    @property
    def simbolo(self) -> str:
        return SIMBOLOS[self.balde]

    @property
    def rotulo_cobertura(self) -> str:
        if self.cobertura_da_meta is None:
            return "—"
        return "%.0f%% da meta" % (100 * self.cobertura_da_meta)


@dataclass(frozen=True)
class Resumo:
    """O que a interface mostra ANTES da grade.

    Perplexity tinha razão no ponto: um mapa inteiro em alerta é ignorado. A
    leitura começa pelo agregado por severidade e só então desce à célula.
    """
    contagem: Dict[str, int]
    acionaveis: Sequence[Celula]
    verificado_em: date
    reguas_por_verificar: Sequence[str]

    @property
    def total(self) -> int:
        return sum(self.contagem.values())

    def frase(self) -> str:
        """Uma linha honesta, com os três baldes separados."""
        return ("%d de %d unidades com lacuna da fonte; %d ainda não apuradas por "
                "nós; %d de ausência planejada."
                % (self.contagem.get(Balde.LACUNA, 0), self.total,
                   self.contagem.get(Balde.NOSSA, 0),
                   self.contagem.get(Balde.PLANEJADA, 0)))


# ─────────────────────────── lógica (pura) ───────────────────────────
def balde_de(av: lat.Avaliacao) -> str:
    """A ordem das perguntas é o método.

    Pendência nossa vem antes de tudo: se ainda não olhamos, não há afirmação a
    fazer sobre o órgão, e classificar de outro jeito seria emprestar ao órgão uma
    falha nossa.
    """
    if av.pendencias_nossas:
        return Balde.NOSSA
    if av.temporal == lat.Temporal.AUSENCIA_PLANEJADA:
        return Balde.PLANEJADA
    if av.tem_alerta:
        return Balde.LACUNA
    return Balde.EM_DIA


def montar(avaliacoes: Sequence[lat.Avaliacao],
           fonte: cat.Fonte = None) -> Sequence[Celula]:
    """Avaliações viram células. Nada aqui desenha."""
    fonte = cat.ANVISA_PARA if fonte is None else fonte
    return tuple(Celula(unidade=av.unidade or fonte.id,
                        balde=balde_de(av),
                        estado=av.temporal,
                        confianca=av.confianca,
                        cobertura_da_meta=av.cobertura_da_meta,
                        motivo=av.motivo,
                        regua=fonte.regua_fonte,
                        regua_verificada=fonte.regua_verificada)
                 for av in avaliacoes)


def acionaveis(celulas: Sequence[Celula], quantas: int = 3) -> Sequence[Celula]:
    """As lacunas em que vale gastar o próximo pedido de informação.

    Ordena por distância da meta declarada, do pior para o melhor. Cobertura
    desconhecida vai para o fim: não se pede o que não se sabe se falta.
    """
    lacunas = [c for c in celulas if c.balde == Balde.LACUNA]
    lacunas.sort(key=lambda c: (c.cobertura_da_meta is None,
                                c.cobertura_da_meta if c.cobertura_da_meta is not None else 0.0))
    return tuple(lacunas[:quantas])


def resumo(celulas: Sequence[Celula], verificado_em: date,
           catalogo: Sequence[cat.Fonte] = None) -> Resumo:
    contagem = {b: 0 for b in Balde.ORDEM}
    for c in celulas:
        contagem[c.balde] = contagem.get(c.balde, 0) + 1
    catalogo = cat.CATALOGO if catalogo is None else catalogo
    return Resumo(contagem=contagem,
                  acionaveis=acionaveis(celulas),
                  verificado_em=verificado_em,
                  reguas_por_verificar=tuple(f.id for f in catalogo
                                             if not f.regua_verificada))


def grade(celulas: Sequence[Celula],
          colunas: int = COLUNAS_DA_GRADE) -> Sequence[Tuple[Celula, int, int]]:
    """Posiciona as células numa grade, em ordem alfabética.

    Alfabética, e não por gravidade, de propósito: ordenar por gravidade faria a
    grade parecer um ranking de alimentos perigosos, que é exatamente a leitura
    que esta fonte NÃO sustenta — o dado é sobre irregularidade regulatória, não
    sobre risco à saúde.
    """
    fora = []
    for i, c in enumerate(sorted(celulas, key=lambda x: x.unidade)):
        fora.append((c, i % colunas, i // colunas))
    return tuple(fora)


def texto_do_cartao(c: Celula) -> str:
    """Cartão de evidência: por que esta célula tem esta cor.

    É o que separa painel de instrumento auditável. Quem discordar precisa poder
    ver a régua, a origem da régua e o motivo sem sair da tela.
    """
    linhas = ["<b>%s</b>" % c.unidade,
              "estado: %s" % c.estado,
              "leitura: %s" % c.balde,
              "confiança: %s" % c.confianca,
              "cobertura: %s" % c.rotulo_cobertura,
              "",
              "por quê: %s" % c.motivo,
              "",
              "régua: %s" % c.regua]
    if not c.regua_verificada:
        linhas.append("<i>régua ainda não conferida no documento primário</i>")
    return "<br>".join(linhas)


# ─────────────────────────── desenho ───────────────────────────
def figura(celulas: Sequence[Celula], titulo: str = "Mapa de frieza — PARA"):
    """Grade em Plotly. Uma série por balde, para a legenda ser o vocabulário."""
    import plotly.graph_objects as go

    posicoes = grade(celulas)
    fig = go.Figure()
    for balde in Balde.ORDEM:
        pontos = [(c, x, y) for c, x, y in posicoes if c.balde == balde]
        if not pontos:
            continue
        fig.add_trace(go.Scatter(
            x=[x for _, x, _ in pontos],
            y=[-y for _, _, y in pontos],          # topo para baixo, como se lê
            mode="markers+text",
            name="%s (%d)" % (balde, len(pontos)),
            marker=dict(size=42, color=CORES[balde], symbol=SIMBOLOS[balde],
                        line=dict(width=1.5, color=CONTORNOS[balde])),
            text=[c.unidade for c, _, _ in pontos],
            textposition="bottom center",
            textfont=dict(size=11, color="#3a4048"),
            hovertext=[texto_do_cartao(c) for c, _, _ in pontos],
            hoverinfo="text",
        ))
    linhas = (len(celulas) + COLUNAS_DA_GRADE - 1) // COLUNAS_DA_GRADE
    fig.update_layout(
        title=dict(text=titulo, x=0.02, xanchor="left"),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.08, x=0),
        # Sem `scaleanchor`: travar a proporção espremia a grade num terço da
        # largura e deixava o resto vazio. A grade é um arranjo de rótulos, não
        # um espaço métrico — nada aqui se mede em distância.
        xaxis=dict(visible=False, range=[-0.6, COLUNAS_DA_GRADE - 0.4]),
        yaxis=dict(visible=False, range=[-linhas + 0.4, 0.6]),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=130 + 92 * linhas,
        margin=dict(l=30, r=30, t=60, b=70),
    )
    return fig


# ─────────────────────────── aplicação ───────────────────────────
def app(caminho_csv: str = "dados/para_2024.csv", ciclo: int = 2024,
        hoje: Optional[date] = None) -> None:
    """Página Streamlit. Importada tarde, para o resto do módulo não depender dela."""
    import streamlit as st

    from painel_san.modulos.alimento_seguro import para

    hoje = hoje or date.today()
    avaliacoes = para.avaliar_ciclo(para.ler_csv(caminho_csv), ciclo, hoje)
    celulas = montar(avaliacoes)
    r = resumo(celulas, hoje)

    st.title("Onde o dado não permite vigiar")
    st.caption(
        "Este painel não diz se o alimento está seguro. Diz se o dado público "
        "permite saber — e, quando não permite, por quê. Última verificação "
        "automatizada: %s." % r.verificado_em.isoformat())

    colunas = st.columns(len(Balde.ORDEM))
    for coluna, balde in zip(colunas, Balde.ORDEM):
        coluna.metric(balde, r.contagem.get(balde, 0))

    st.plotly_chart(figura(celulas), use_container_width=True)

    st.subheader("Onde vale gastar o próximo pedido de informação")
    for c in r.acionaveis:
        st.markdown("**%s** — %s. %s" % (c.unidade, c.rotulo_cobertura, c.motivo))

    st.subheader("O que esta fonte NÃO permite concluir")
    st.markdown(
        "- que um alimento seja seguro ou inseguro para consumo\n"
        "- risco à saúde de quem o consome: resíduo, irregularidade regulatória e "
        "risco são três coisas distintas\n"
        "- ranking estável entre alimentos — parte dos intervalos de confiança se "
        "sobrepõe\n"
        "- qualquer recorte por estado ou município: a fonte não desagrega")

    if r.reguas_por_verificar:
        st.info("Réguas ainda não conferidas no documento primário: %s."
                % ", ".join(r.reguas_por_verificar))
