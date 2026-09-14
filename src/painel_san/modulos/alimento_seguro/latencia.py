# -*- coding: utf-8 -*-
"""
Avaliação da lacuna: quão longe cada fonte está da régua que ela mesma declarou.

MÓDULO PURO
    Recebe uma `Fonte` e o que foi observado dela; devolve uma avaliação. Não
    consulta rede, não lê arquivo, não imprime. Quem observa é `registrador.py`;
    quem desenha é `pagina.py`.

A MÉTRICA
    Latência relativa = tempo desde a última medição usável ÷ periodicidade
    prometida.

        1,0  em dia
        2,5  dois anos e meio de atraso sobre um ciclo anual
        inf  nunca medido

    O denominador vem sempre do compromisso do próprio órgão, nunca de um
    parâmetro nosso. Normalizar assim torna comparáveis fontes que não têm nada
    em comum: o SISAGUA deve medir a cada três meses e o PARA a cada trinta e
    seis, e mesmo assim dá para dizer qual dos dois está mais longe do próprio
    compromisso.

POR QUE NÃO EXISTE UM ESTADO ÚNICO
    Uma fonte pode estar em dia e ser inútil. O PARA do ciclo 2024 é atual,
    ilegível por máquina, e em seis dos catorze alimentos ficou abaixo do mínimo
    amostral que a Anvisa calculou. São três falhas independentes, com remédios
    diferentes — publicar em CSV não resolve amostra pequena, e coletar mais
    amostras não resolve o PDF.

    Colapsar isso numa cor só faria o mapa mentir. Cada dimensão é avaliada e
    reportada em separado; a visualização escolhe qual está mostrando.
"""
import math
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from painel_san.modulos.alimento_seguro.fontes import Fonte, Formato


# ─────────────────────────── estados ───────────────────────────
class Temporal:
    NO_PRAZO = "no prazo"
    ATRASADO = "atrasado"
    NUNCA_MEDIDO = "nunca medido"
    AUSENCIA_PLANEJADA = "ausência planejada"
    SEM_CALENDARIO = "sem calendário"


class Legibilidade:
    LEGIVEL = "legível por máquina"
    ILEGIVEL = "ilegível por máquina"


class Amostral:
    SUFICIENTE = "suficiente"
    INSUFICIENTE = "insuficiente"
    NAO_AVALIAVEL = "não avaliável"


class Granularidade:
    DISPONIVEL = "disponível"
    NAO_DESAGREGAVEL = "não desagregável"


# Tolerância antes de chamar de atraso. Uma fonte semestral que publica com duas
# semanas de folga não está atrasada — está publicando. Sem isso, toda fonte
# aparece vermelha no dia seguinte ao vencimento, e o instrumento vira alarme
# constante, que é o mesmo que nenhum alarme.
FOLGA = 1.15


@dataclass(frozen=True)
class Observacao:
    """O que se viu de uma fonte, num recorte específico.

    `unidade` é o que se está perguntando — um alimento no PARA, um município no
    SISAGUA. Fica opcional porque parte das perguntas é sobre a fonte inteira.
    """
    ultima_medicao: Optional[date] = None
    n_amostras: Optional[int] = None
    unidade: Optional[str] = None
    planejada_para_depois: bool = False


@dataclass(frozen=True)
class Avaliacao:
    fonte_id: str
    unidade: Optional[str]
    latencia_relativa: float
    meses_desde_medicao: Optional[float]
    temporal: str
    legibilidade: str
    amostral: str
    granularidade: str
    motivo: str

    @property
    def alertas_da_unidade(self) -> Tuple[str, ...]:
        """O que está errado NESTE recorte — este alimento, este município.

        Ausência planejada não entra: o morango não medido em 2024 está no plano
        para 2025. É o caso que mais importa acertar, e é o que separa medição de
        denúncia."""
        fora = []
        if self.temporal in (Temporal.ATRASADO, Temporal.NUNCA_MEDIDO):
            fora.append(self.temporal)
        if self.amostral == Amostral.INSUFICIENTE:
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
    return (fim - inicio).days / 30.44


def latencia_relativa(ultima_medicao: Optional[date],
                      periodicidade_meses: Optional[int],
                      hoje: date) -> float:
    """Quantas vezes o prazo prometido já passou desde a última medição.

    Devolve infinito quando nunca se mediu — e é infinito mesmo, não um número
    grande: não há razão para ordenar entre duas fontes que nunca mediram.
    """
    if periodicidade_meses is None:
        return 0.0                      # registro contínuo não acumula atraso
    if ultima_medicao is None:
        return math.inf
    if periodicidade_meses <= 0:
        raise ValueError("periodicidade precisa ser positiva: %r" % periodicidade_meses)
    return meses_entre(ultima_medicao, hoje) / periodicidade_meses


def _temporal(fonte: Fonte, obs: Observacao, lat: float) -> Tuple[str, str]:
    if obs.ultima_medicao is None and obs.planejada_para_depois:
        return (Temporal.AUSENCIA_PLANEJADA,
                "sem medição, mas o cronograma do órgão prevê para um ciclo futuro")
    if not fonte.tem_calendario:
        return (Temporal.SEM_CALENDARIO,
                "registro atualizado por ato normativo, sem calendário de medição")
    if obs.ultima_medicao is None:
        return Temporal.NUNCA_MEDIDO, "nenhuma medição registrada"
    if lat > FOLGA:
        return (Temporal.ATRASADO,
                "%.1f vezes o prazo de %d meses declarado em: %s"
                % (lat, fonte.periodicidade_meses, fonte.regua_fonte))
    return Temporal.NO_PRAZO, "dentro do prazo declarado pelo órgão"


def _amostral(fonte: Fonte, obs: Observacao) -> Tuple[str, str]:
    if fonte.minimo_amostral is None or obs.n_amostras is None:
        return Amostral.NAO_AVALIAVEL, ""
    if obs.n_amostras < fonte.minimo_amostral:
        return (Amostral.INSUFICIENTE,
                "%d amostras, contra o mínimo de %d que o próprio órgão calcula (%s)"
                % (obs.n_amostras, fonte.minimo_amostral, fonte.regua_minimo))
    return Amostral.SUFICIENTE, ""


def avaliar(fonte: Fonte, obs: Observacao, hoje: date,
            eixo_pedido: Optional[str] = None) -> Avaliacao:
    """Avalia uma fonte num recorte, em todas as dimensões de uma vez.

    `eixo_pedido` é o nível de desagregação que a pergunta exige — "uf",
    "municipio". Se a fonte não desagrega ali, isso é falha de granularidade, e
    não de existência do dado: ele existe, só não nesse nível.
    """
    lat = latencia_relativa(obs.ultima_medicao, fonte.periodicidade_meses, hoje)
    temporal, motivo = _temporal(fonte, obs, lat)
    amostral, motivo_amostral = _amostral(fonte, obs)

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
        meses_desde_medicao=(meses_entre(obs.ultima_medicao, hoje)
                             if obs.ultima_medicao else None),
        temporal=temporal,
        legibilidade=legibilidade,
        amostral=amostral,
        granularidade=granularidade,
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
