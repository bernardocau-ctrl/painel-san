# -*- coding: utf-8 -*-
"""
Avaliação da lacuna: quão longe cada fonte está da régua que ela mesma declarou.

MÓDULO PURO
    Recebe uma `Fonte` e o que foi observado dela; devolve uma avaliação. Não
    consulta rede, não lê arquivo, não imprime. Quem observa é `registrador.py`;
    quem desenha é `pagina.py`.

MEDIR NÃO É PUBLICAR — E SÓ UMA DAS DUAS É OBSERVÁVEL DAQUI
    Esta é a distinção que mais custou a entrar, e a que mais sustenta o
    instrumento. Uma observação tem duas datas, e elas respondem perguntas
    diferentes:

        data_referencia   quando a medição ocorreu, ou a que ciclo ela se refere
        data_publicacao   quando o resultado ficou publicamente disponível

    De fora do órgão, só a segunda se verifica. A primeira vem do que o documento
    declara — quando declara.

    A consequência é dura, e é o ponto: **este módulo não sabe se o órgão mediu.**
    Sabe se o resultado apareceu. Dizer "não mediram" quando o que se viu foi
    "não publicaram" é a afirmação que não se sustenta, e é a primeira que um
    órgão contrariado derrubaria.

    Por isso toda avaliação carrega `base_temporal`, dizendo em qual das duas
    datas ela se apoiou, e o texto do motivo muda junto.

A MÉTRICA
    Latência relativa = tempo desde a última data usável ÷ periodicidade
    prometida.

        1,0  em dia
        2,5  dois ciclos e meio desde a última
        inf  nada localizado

    O denominador vem sempre do compromisso do próprio órgão, nunca de um
    parâmetro nosso. Normalizar assim torna comparáveis fontes que não têm nada
    em comum: o SISAGUA deve medir a cada três meses e o PARA a cada trinta e
    seis, e mesmo assim dá para dizer qual está mais longe do próprio compromisso.

    Mas a latência serve para ORDENAR e descrever, não para decidir. Quem decide
    o estado é a tolerância em dias declarada no catálogo — ver `_temporal`.

POR QUE NÃO EXISTE UM ESTADO ÚNICO
    Uma fonte pode estar em dia e ser inútil. O PARA do ciclo 2024 é atual,
    ilegível por máquina, e em seis dos catorze alimentos ficou abaixo da meta
    amostral que a Anvisa declarou. São três falhas independentes, com remédios
    diferentes — publicar em CSV não resolve amostra pequena, e coletar mais
    amostras não resolve o PDF.

    Colapsar isso numa cor só faria o mapa mentir. Cada dimensão é avaliada e
    reportada em separado; a visualização escolhe qual está mostrando.
"""
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from painel_san.modulos.alimento_seguro.fontes import Fonte

DIAS_NO_MES = 30.44


# ─────────────────────────── estados ───────────────────────────
class Temporal:
    NO_PRAZO = "no prazo"
    PENDENTE = "atualização pendente"          # venceu, mas dentro da tolerância
    ATRASADO = "atraso de disponibilidade"
    ATRASO_PROLONGADO = "indisponibilidade persistente"
    NADA_LOCALIZADO = "nada localizado"
    AUSENCIA_PLANEJADA = "ausência planejada"
    SEM_CALENDARIO = "sem calendário"


class Legibilidade:
    LEGIVEL = "legível por máquina"
    ILEGIVEL = "ilegível por máquina"


class Amostral:
    ATINGE_A_META = "atinge a meta declarada"
    ABAIXO_DA_META = "abaixo da meta declarada"
    NAO_AVALIAVEL = "não avaliável"


class Granularidade:
    DISPONIVEL = "disponível"
    NAO_DESAGREGAVEL = "não desagregável"


class Base:
    """Em que data a classificação temporal se apoiou.

    A diferença não é de precisão: é da natureza do que se pode afirmar a partir
    de cada uma.
    """
    PUBLICACAO = "publicação"    # observável de fora; sustenta afirmação forte
    REFERENCIA = "referência"    # declarada pelo documento; afirmação mais fraca
    NENHUMA = "nenhuma"


class Confianca:
    """Quanto peso a classificação aguenta.

    Existe porque nem toda cor do painel vale o mesmo. Um atraso apurado contra um
    ato normativo lido no primário, sobre uma data de publicação que o registrador
    observou, é outra coisa que um atraso apurado contra uma periodicidade lida
    numa reportagem, sobre uma data inferida de um PDF.

    As duas podem estar certas. Só não podem ser exibidas como se fossem
    igualmente sólidas.
    """
    ALTA = "alta"
    MODERADA = "moderada"
    BAIXA = "baixa"
    NAO_CLASSIFICAVEL = "não classificável"


@dataclass(frozen=True)
class Observacao:
    """O que se viu de uma fonte, num recorte específico.

    `unidade` é o que se está perguntando — um alimento no PARA, um município no
    SISAGUA. Fica opcional porque parte das perguntas é sobre a fonte inteira.

    As duas datas são independentes de propósito. Ter só uma é o caso comum, e
    qual delas se tem muda o que se pode afirmar.
    """
    data_referencia: Optional[date] = None
    data_publicacao: Optional[date] = None
    n_amostras: Optional[int] = None
    unidade: Optional[str] = None
    planejada_para_depois: bool = False

    @property
    def data_usavel(self) -> Tuple[Optional[date], str]:
        """A data que sustenta a classificação, e de que tipo ela é.

        Prefere a publicação: é a única verificável de fora, e é sobre ela que
        este instrumento tem o direito de falar.
        """
        if self.data_publicacao is not None:
            return self.data_publicacao, Base.PUBLICACAO
        if self.data_referencia is not None:
            return self.data_referencia, Base.REFERENCIA
        return None, Base.NENHUMA


@dataclass(frozen=True)
class Avaliacao:
    fonte_id: str
    unidade: Optional[str]
    latencia_relativa: float
    meses_desde: Optional[float]
    base_temporal: str
    temporal: str
    legibilidade: str
    amostral: str
    cobertura_da_meta: Optional[float]
    granularidade: str
    confianca: str
    motivo: str

    @property
    def alertas_da_unidade(self) -> Tuple[str, ...]:
        """O que está errado NESTE recorte — este alimento, este município.

        Ausência planejada não entra: o morango não medido em 2024 está no plano
        para 2025. É o caso que mais importa acertar, e é o que separa medição de
        denúncia.

        `PENDENTE` também não entra: venceu, mas dentro da tolerância declarada.
        É o estado que impede o painel de ficar vermelho no dia seguinte ao prazo.
        """
        fora = []
        if self.temporal in (Temporal.ATRASADO, Temporal.ATRASO_PROLONGADO,
                             Temporal.NADA_LOCALIZADO):
            fora.append(self.temporal)
        if self.amostral == Amostral.ABAIXO_DA_META:
            fora.append(self.amostral)
        if self.granularidade == Granularidade.NAO_DESAGREGAVEL:
            fora.append(self.granularidade)
        return tuple(fora)

    @property
    def alertas_da_fonte(self) -> Tuple[str, ...]:
        """O que está errado na FONTE INTEIRA, igual para todos os recortes.

        Separado de propósito. A ilegibilidade do PARA vale para os catorze
        alimentos ao mesmo tempo: repeti-la em cada célula do mapa pintaria tudo
        de vermelho e afogaria o que varia de célula para célula. Ela é atributo
        da camada, mostrado uma vez."""
        return (self.legibilidade,) if self.legibilidade == Legibilidade.ILEGIVEL else ()

    @property
    def tem_alerta(self) -> bool:
        """Alerta sobre este recorte. É o que decide a cor da célula."""
        return bool(self.alertas_da_unidade)


# ─────────────────────────── cálculo ───────────────────────────
def meses_entre(inicio: date, fim: date) -> float:
    """Meses corridos, com fração. Aproxima o mês por 30,44 dias — a precisão de
    dia não importa aqui e evita a álgebra de calendário."""
    return (fim - inicio).days / DIAS_NO_MES


def latencia_relativa(desde: Optional[date],
                      periodicidade_meses: Optional[int],
                      hoje: date) -> float:
    """Quantas vezes o prazo prometido já passou desde a última data usável.

    Devolve infinito quando não há data — e é infinito mesmo, não um número
    grande: não há razão para ordenar entre duas fontes das quais nada se achou.
    """
    if periodicidade_meses is None:
        return 0.0                      # registro contínuo não acumula atraso
    if desde is None:
        return math.inf
    if periodicidade_meses <= 0:
        raise ValueError("periodicidade precisa ser positiva: %r" % periodicidade_meses)
    return meses_entre(desde, hoje) / periodicidade_meses


def _temporal(fonte: Fonte, obs: Observacao, hoje: date) -> Tuple[str, str, str]:
    """Devolve (estado, base usada, motivo).

    O estado sai de DIAS, não de razão. A régua percentual antiga — 15% do prazo,
    igual para todas as fontes — dava cinco meses e meio de perdão ao PARA e
    catorze dias ao SISAGUA: quanto mais longo o prazo, maior o perdão, que é o
    contrário do que se queria. Agora cada fonte declara sua tolerância em dias,
    no catálogo, com a justificativa ao lado.
    """
    desde, base = obs.data_usavel

    if desde is None and obs.planejada_para_depois:
        return (Temporal.AUSENCIA_PLANEJADA, base,
                "sem resultado publicado, mas o cronograma do próprio órgão prevê "
                "a medição para um ciclo futuro")
    if not fonte.tem_calendario:
        return (Temporal.SEM_CALENDARIO, base,
                "registro atualizado por ato normativo, sem calendário de medição")
    if desde is None:
        return (Temporal.NADA_LOCALIZADO, base,
                "nenhum resultado localizado no recurso consultado — o que não "
                "permite concluir que a medição não tenha ocorrido")

    prazo_dias = fonte.periodicidade_meses * DIAS_NO_MES
    vencido_ha = (hoje - desde).days - prazo_dias
    tolerancia = fonte.tolerancia_dias or 0

    if base == Base.PUBLICACAO:
        origem = "última publicação localizada em %s" % desde.isoformat()
    else:
        origem = ("dado referente a %s, data de publicação desconhecida"
                  % desde.isoformat())

    if vencido_ha <= 0:
        return (Temporal.NO_PRAZO, base,
                "%s — dentro do prazo declarado pelo órgão" % origem)
    if vencido_ha <= tolerancia:
        return (Temporal.PENDENTE, base,
                "%s — venceu há %d dias, dentro da tolerância de %d dias (%s)"
                % (origem, vencido_ha, tolerancia, fonte.regua_tolerancia))

    estado = (Temporal.ATRASO_PROLONGADO if vencido_ha >= 2 * prazo_dias
              else Temporal.ATRASADO)
    return (estado, base,
            "%s — %d dias além do prazo de %d meses declarado em: %s"
            % (origem, vencido_ha, fonte.periodicidade_meses, fonte.regua_fonte))


def _amostral(fonte: Fonte, obs: Observacao) -> Tuple[str, Optional[float], str]:
    """Cobertura da meta declarada. Nunca a palavra "insuficiente".

    A diferença não é de estilo. "85 de 231 amostras, 37% da meta que a Anvisa
    calculou para este ciclo, na p. 30 do relatório" é verificável linha a linha
    e o denominador está à vista. "Amostra insuficiente" é uma afirmação
    estatística sobre representatividade no país, que exigiria saber
    população-alvo, desenho probabilístico, perdas e desfecho — nada disso está
    publicado, e nada disso nós recalculamos.

    A segunda frase é mais forte, e é a que derruba o instrumento se for contestada.
    """
    if fonte.meta_amostral is None or obs.n_amostras is None:
        return Amostral.NAO_AVALIAVEL, None, ""
    cobertura = obs.n_amostras / fonte.meta_amostral
    texto = ("%d de %d amostras — %.0f%% da meta que o próprio órgão declarou (%s)"
             % (obs.n_amostras, fonte.meta_amostral, cobertura * 100, fonte.regua_meta))
    if cobertura < 1.0:
        return Amostral.ABAIXO_DA_META, cobertura, texto
    return Amostral.ATINGE_A_META, cobertura, texto


def _confianca(fonte: Fonte, temporal: str, base: str) -> str:
    """Quanto peso a classificação temporal aguenta.

    Duas perguntas, nesta ordem:

        a régua foi conferida no documento primário?
        a data veio de publicação observada, ou de referência declarada?

    Não é sofisticado, de propósito. Os dois ingredientes já existiam — um no
    catálogo, outro na observação — e o que faltava era só parar de exibir todas
    as cores do painel como igualmente sólidas.
    """
    if temporal == Temporal.SEM_CALENDARIO:
        # Não há classificação temporal a respeito da qual ter confiança.
        return Confianca.NAO_CLASSIFICAVEL
    if temporal == Temporal.NADA_LOCALIZADO:
        # Não se distingue "nunca mediram" de "mediram e não publicaram" de
        # "publicaram em lugar que não monitoramos". Enquanto não se distingue, a
        # classificação não merece peso.
        return Confianca.BAIXA
    if temporal == Temporal.AUSENCIA_PLANEJADA:
        # Repousa inteiramente sobre o cronograma publicado ter sido lido.
        return Confianca.ALTA if fonte.regua_verificada else Confianca.MODERADA
    if fonte.regua_verificada and base == Base.PUBLICACAO:
        return Confianca.ALTA
    if fonte.regua_verificada or base == Base.PUBLICACAO:
        return Confianca.MODERADA
    return Confianca.BAIXA


def avaliar(fonte: Fonte, obs: Observacao, hoje: date,
            eixo_pedido: Optional[str] = None) -> Avaliacao:
    """Avalia uma fonte num recorte, em todas as dimensões de uma vez.

    `eixo_pedido` é o nível de desagregação que a pergunta exige — "uf",
    "municipio". Se a fonte não desagrega ali, isso é falha de granularidade, e
    não de existência do dado: ele existe, só não nesse nível.
    """
    desde, _ = obs.data_usavel
    lat = latencia_relativa(desde, fonte.periodicidade_meses, hoje)
    temporal, base, motivo = _temporal(fonte, obs, hoje)
    amostral, cobertura, motivo_amostral = _amostral(fonte, obs)

    legibilidade = Legibilidade.LEGIVEL if fonte.legivel else Legibilidade.ILEGIVEL
    if not fonte.legivel:
        motivo = (motivo + "; " if motivo else "") + "publicado em %s" % fonte.formato
    if motivo_amostral:
        motivo = (motivo + "; " if motivo else "") + motivo_amostral

    granularidade = Granularidade.DISPONIVEL
    if eixo_pedido is not None and not fonte.desagrega_por(eixo_pedido):
        granularidade = Granularidade.NAO_DESAGREGAVEL
        motivo = ((motivo + "; " if motivo else "")
                  + "não desagrega por %r; disponível em %s"
                  % (eixo_pedido, ", ".join(fonte.granularidade) or "nenhum eixo"))

    return Avaliacao(
        fonte_id=fonte.id,
        unidade=obs.unidade,
        latencia_relativa=lat,
        meses_desde=meses_entre(desde, hoje) if desde else None,
        base_temporal=base,
        temporal=temporal,
        legibilidade=legibilidade,
        amostral=amostral,
        cobertura_da_meta=cobertura,
        granularidade=granularidade,
        confianca=_confianca(fonte, temporal, base),
        motivo=motivo,
    )


def planejada_para_depois(cronograma: dict, unidade: str, ciclo_atual: int) -> bool:
    """True se a unidade não é medida agora mas está marcada para ciclo futuro.

    Alimenta `Observacao.planejada_para_depois`. Unidade fora do cronograma
    devolve False: não estar no plano é outra coisa, e mais grave, que estar
    planejada para depois."""
    ciclos = cronograma.get(unidade)
    if not ciclos:
        return False
    return ciclo_atual not in ciclos and any(c > ciclo_atual for c in ciclos)
