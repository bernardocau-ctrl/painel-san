# -*- coding: utf-8 -*-
"""
Conector do PARA: do relatório em PDF à avaliação por alimento.

POR QUE O PARA É O PILOTO
    É a única fonte do catálogo que reúne as três coisas que o módulo precisa
    exercitar: meta amostral declarada pelo próprio órgão, cronograma publicado
    que permite separar ausência planejada de lacuna, e resultado por unidade —
    o alimento. Nas outras quatro, uma dessas pernas falta.

    É também a fonte onde a ilegibilidade dói mais: mais de 35 mil amostras desde
    2001, e nem o arquivo que a Anvisa chama de "Dados Brutos" é planilha.

A CADEIA DE EVIDÊNCIA
    regra oficial → catálogo → extração → validação → tabela curada → avaliação

    Cada elo é verificável sozinho. A extração não é confiada: ela é conferida
    contra dois totais que a própria Anvisa publica no relatório, e se não fechar,
    nada é gravado. A tabela curada que sai daqui é pequena o bastante para uma
    pessoa conferir à mão contra o PDF — e essa é a intenção, não um acaso.

POR QUE CSV, E NÃO PARQUET
    Contraria a regra do módulo SAN, como o registrador já contrariava, e pela
    mesma razão de fundo: o valor aqui é alguém poder auditar. São catorze linhas
    que cabem numa tela, vindas de um PDF que ninguém mais extraiu. Em Parquet, o
    revisor teria que escrever código para checar o que o olho checa em um minuto.

O PDF NÃO ESTÁ NO REPOSITÓRIO
    São 2,8 MB de documento público que a Anvisa hospeda. Fica de fora, e o que se
    versiona é a tabela extraída mais os totais de validação. Quem quiser conferir
    baixa o relatório e roda `python -m painel_san.modulos.alimento_seguro.para` —
    se a extração divergir do que está gravado, o programa recusa.
"""
import argparse
import csv
import io
import math
import os
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Dict, Optional, Sequence, Tuple

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro import latencia as lat

# ─────────────────────────── o que o ciclo mediu ───────────────────────────
# Os catorze alimentos do ciclo 2024, na ordem em que o relatório os apresenta.
# O Plano Plurianual 2023-2025 cobre 36 no total — ver `fontes.PARA_CRONOGRAMA`.
ALIMENTOS = {
    # Primeiro ciclo do Plano Plurianual. Grafias exatamente como o relatório as
    # escreve — "Batata-doce" com hífen, que o cronograma escreve sem.
    2023: ("Arroz", "Abacaxi", "Goiaba", "Laranja", "Manga", "Uva", "Alface",
           "Chuchu", "Pimentão", "Tomate", "Alho", "Batata-doce", "Beterraba",
           "Cenoura"),
    2024: ("Aveia", "Milho", "Trigo", "Banana", "Laranja", "Mamão", "Maçã",
           "Pera", "Uva", "Abobrinha", "Couve", "Pepino", "Soja", "Cebola"),
}

# Os dois números que a Anvisa publica no corpo do relatório, e contra os quais a
# extração é conferida. São a única razão pela qual confiar no que sai daqui.
ESPERADO = {
    2023: {"amostras": 3294, "pct_insatisfatorio": 26.1},
    2024: {"amostras": 3084, "pct_insatisfatorio": 20.6},
}

# O ciclo é anual, mas o dado se refere ao ano inteiro. Data de referência é o
# fechamento — nunca a data de publicação, que é outra coisa e não se sabe daqui.
def referencia_do_ciclo(ciclo: int) -> date:
    return date(ciclo, 12, 31)


# O relatório escreve números pequenos por extenso: "Uma amostra foi considerada
# insatisfatória". Sem isto, alimentos com poucas irregularidades saem vazios — e
# sairiam vazios em silêncio, que é o pior modo de falhar.
EXTENSO = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "quatro": 4,
           "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10,
           "onze": 11, "doze": 12, "treze": 13, "quatorze": 14, "catorze": 14,
           "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18,
           "dezenove": 19, "vinte": 20, "nenhuma": 0}

COLUNAS = ("ciclo", "alimento", "n_amostras", "n_insatisfatorias")


@dataclass(frozen=True)
class Resultado:
    """O que o relatório diz de um alimento, num ciclo."""
    ciclo: int
    alimento: str
    n_amostras: int
    n_insatisfatorias: int

    @property
    def pct_insatisfatorio(self) -> float:
        return 100.0 * self.n_insatisfatorias / self.n_amostras


# ─────────────────────────── leitura (puro) ───────────────────────────
def chave(nome: str) -> str:
    """Forma comparável de um nome de alimento: sem acento, sem hífen, minúscula.

    Existe porque o relatório escreve "Maçã" e o cronograma do Plano Plurianual
    escreve "maca". Sem isto, o alimento mais irregular do ciclo poderia não
    encontrar seu próprio cronograma e virar lacuna inexistente.

    O hífen entrou ao ingerir o ciclo 2023: o relatório escreve "Batata-doce" e o
    cronograma, "batata doce". Dois nomes do mesmo alimento, em dois documentos da
    mesma agência. É o tipo de divergência que não dá erro — só faz um alimento
    sumir do painel — e por isso a normalização precisa ser generosa aqui.
    """
    sem = unicodedata.normalize("NFKD", nome.strip().lower().replace("-", " "))
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    return " ".join(sem.split())


def valor(token: str) -> Optional[int]:
    """Número escrito em dígitos ou por extenso. None se não for nenhum dos dois."""
    t = token.strip().lower()
    if t in EXTENSO:
        return EXTENSO[t]
    t = t.replace(".", "").replace(" ", "")
    return int(t) if t.isdigit() else None


def limpar(bruto: str) -> str:
    """Tira o cabeçalho que se repete em toda página e normaliza o espaço.

    "Anvisa – Agência Nacional de Vigilância Sanitária Página 12 de 150" aparece
    entre as frases e quebra as expressões que procuram número seguido de palavra.
    """
    sem_cabecalho = re.sub(
        r"Anvisa\s*–\s*Ag[êe]ncia Nacional de Vigil[âa]ncia Sanit[áa]ria\s*"
        r"P[áa]gina \d+ de \d+", " ", bruto)
    return re.sub(r"\s+", " ", sem_cabecalho)


def extrair(texto: str, ciclo: int) -> Tuple[Sequence[Resultado], Sequence[str]]:
    """Devolve (resultados, alimentos que não saíram).

    DUAS ARMADILHAS, ambas já custaram caro:

    1. O sumário repete os títulos das seções. Procurar a PRIMEIRA ocorrência de
       "a. Cebola" acha o índice, onde não há número nenhum. Usa-se a ÚLTIMA.

    2. Extrair da TABELA é menos confiável que do texto corrido. A Tabela 3 do
       relatório 2024 traz "trigo 224"; a prosa diz 234 — e só com 234 a soma
       fecha nos 3.084 que a Anvisa publica. Preferir sempre a prosa.

       A causa apareceu depois: o PDF QUEBRA DÍGITOS entre trechos de texto.
       A banana sai como "22 2 amostras" e o trigo como "2 34 amostras". Por isso
       a expressão aceita espaço dentro do número e `valor` o remove. Na tabela,
       a mesma quebra faz o "3" virar coluna e o valor chegar truncado.

       Isso é, por si, evidência do que o catálogo afirma sobre esta fonte: um
       arquivo em que o número 234 não está escrito como 234 não é dado aberto,
       por mais que caiba num PDF.

    A faixa `[a-h]` não é arbitrária: o relatório reinicia a numeração das seções
    a cada capítulo — cereais vão de a a c, frutas de a a c, e assim por diante.
    Nenhum capítulo passa de três itens em 2024, e oito dá folga suficiente sem
    abrir a porta para casar com prosa qualquer que tenha letra seguida de ponto.
    """
    fora, faltaram = [], []
    for alimento in ALIMENTOS[ciclo]:
        marcas = list(re.finditer(r"[a-h]\.\s*%s\b" % re.escape(alimento), texto))
        if not marcas:
            faltaram.append(alimento)
            continue
        bloco = texto[marcas[-1].end(): marcas[-1].end() + 1200]
        mt = re.search(r"[Ff]oram analisadas ([\d\. ]{2,7}?) amostras", bloco)
        mi = re.search(r"([\wáéíóúâêôãõç\.]+) amostras? (?:foram|foi) "
                       r"considerad\w*\s*insatisfat", bloco)
        n = valor(mt.group(1)) if mt else None
        k = valor(mi.group(1)) if mi else None
        if n is None or k is None:
            faltaram.append(alimento)
            continue
        fora.append(Resultado(ciclo, alimento, n, k))
    return tuple(fora), tuple(faltaram)


# ─────────────────────────── validação (puro) ───────────────────────────
def valida(resultados: Sequence[Resultado], ciclo: int,
           faltaram: Sequence[str] = ()) -> Tuple[bool, str]:
    """Confere a extração contra os totais que a Anvisa publica.

    Sem isto, o módulo inteiro repousaria sobre expressões regulares aplicadas a
    um PDF — e um PDF muda de diagramação sem avisar ninguém. A validação é o que
    separa "extraí" de "extraí certo", e é ela que autoriza gravar.
    """
    esperado = ESPERADO.get(ciclo)
    if esperado is None:
        return False, "não há totais publicados registrados para o ciclo %d" % ciclo
    if faltaram:
        return False, "não extraí %s" % ", ".join(faltaram)
    if len(resultados) != len(ALIMENTOS[ciclo]):
        return False, ("extraí %d alimentos, o ciclo tem %d"
                       % (len(resultados), len(ALIMENTOS[ciclo])))
    n = sum(r.n_amostras for r in resultados)
    if n != esperado["amostras"]:
        return False, "somei %d amostras, o relatório diz %d" % (n, esperado["amostras"])
    k = sum(r.n_insatisfatorias for r in resultados)
    pct = 100.0 * k / n
    if abs(pct - esperado["pct_insatisfatorio"]) > 0.05:
        return False, ("%.1f%% insatisfatórias, o relatório diz %.1f%%"
                       % (pct, esperado["pct_insatisfatorio"]))
    return True, ("%d amostras, %.1f%% insatisfatórias — bate com os dois totais "
                  "publicados" % (n, pct))


def wilson(k: int, n: int, z: float = 1.6449) -> Tuple[float, float]:
    """Intervalo de confiança de Wilson, em pontos percentuais.

    z = 1,6449 dá 90%, que é o intervalo que a própria Anvisa adotou no ciclo
    2024 — ela documenta ter baixado de 95% para 90% por limitação logística de
    coleta. Usar 95% aqui seria aplicar régua nossa a dado dela.

    Wilson e não normal simples porque com n pequeno e p perto de zero o intervalo
    normal escapa para baixo de zero. O trigo, com 5 irregulares em 234, é
    exatamente esse caso.
    """
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / d
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (100 * max(0.0, centro - meia), 100 * min(1.0, centro + meia))


def distinguiveis(a: Resultado, b: Resultado, z: float = 1.6449) -> bool:
    """True se os intervalos de a e b não se sobrepõem.

    Serve para conter a leitura do próprio painel: "o pepino tem mais resíduo que
    a banana" é afirmação que a amostragem sustenta; "a maçã tem mais que a uva"
    não é, e as duas pareceriam igualmente verdadeiras numa barra ordenada.
    """
    ia, ib = wilson(a.n_insatisfatorias, a.n_amostras, z), wilson(b.n_insatisfatorias, b.n_amostras, z)
    return ia[0] > ib[1] or ib[0] > ia[1]


# ─────────────────────────── ponte com a avaliação ───────────────────────────
def observacoes(resultados: Sequence[Resultado], ciclo: int,
                cronograma: Dict[str, tuple] = None) -> Sequence[lat.Observacao]:
    """Uma observação por alimento do PLANO — não por alimento medido.

    A diferença é o módulo inteiro. Percorrer só os catorze medidos produziria um
    painel que mostra o que existe; percorrer os trinta e seis do plano produz um
    painel que mostra o que falta, que é o objeto.

    QUATRO desfechos saem daqui, e distingui-los é o ponto:

        medido no ciclo      → tem data e n, avalia cobertura da meta
        marcado para depois  → ausência planejada, não é lacuna
        ciclo não ingerido   → pendência NOSSA. O alimento é medido num ciclo
                               anterior cujo relatório ainda não extraímos. Não
                               alerta contra a Anvisa, porque não sabemos nada
                               sobre ele — só sabemos que não fomos ver.
        ingerido e ausente   → aí sim é achado: lemos o relatório do ciclo em que
                               ele deveria estar, e ele não estava.

    A terceira linha foi acrescentada depois de ver o resultado real: com apenas o
    ciclo 2024 extraído, doze dos trinta e seis alimentos acendiam como lacuna da
    Anvisa quando a lacuna era a nossa lista de tarefas. Um painel assim diria o
    contrário do verdadeiro — e seria derrubado por quem tivesse lido o relatório
    de 2023.
    """
    cronograma = cat.PARA_CRONOGRAMA if cronograma is None else cronograma

    # Ordenar por ciclo antes de indexar: a laranja é medida nos três ciclos e a
    # uva em dois, e sem isto qual medição prevalece dependeria da ordem em que os
    # CSVs foram concatenados. O resultado ficaria certo por acidente hoje e
    # errado amanhã, sem nada falhar — a forma de defeito que este projeto mais
    # já pagou. A medição mais recente é a que vale.
    medidos = {}
    for r in sorted(resultados, key=lambda x: x.ciclo):
        medidos[chave(r.alimento)] = r
    ingeridos = {r.ciclo for r in resultados}
    fora = []
    for alimento in sorted(cronograma):
        r = medidos.get(chave(alimento))
        if r is not None:
            fora.append(lat.Observacao(data_referencia=referencia_do_ciclo(r.ciclo),
                                       n_amostras=r.n_amostras, unidade=alimento))
            continue
        passados = [c for c in cronograma.get(alimento, ()) if c <= ciclo]
        fora.append(lat.Observacao(
            unidade=alimento,
            planejada_para_depois=lat.planejada_para_depois(
                cronograma, alimento, ciclo),
            nao_apurado=bool(passados) and not any(c in ingeridos for c in passados)))
    return tuple(fora)


def avaliar_ciclo(resultados: Sequence[Resultado], ciclo: int, hoje: date,
                  eixo_pedido: Optional[str] = None,
                  cronograma: Dict[str, tuple] = None) -> Sequence[lat.Avaliacao]:
    """Avalia os 36 alimentos do plano contra a régua do PARA."""
    return tuple(lat.avaliar(cat.ANVISA_PARA, o, hoje, eixo_pedido)
                 for o in observacoes(resultados, ciclo, cronograma))


# ─────────────────────────── entrada e saída ───────────────────────────
def ler_pdf(caminho: str, pular_paginas: int = 25) -> str:
    """Texto do corpo do relatório. Importa pypdf só aqui, para o resto ficar puro."""
    from pypdf import PdfReader
    r = PdfReader(caminho)
    return limpar("\n".join((p.extract_text() or "") for p in r.pages[pular_paginas:]))


def gravar(resultados: Sequence[Resultado], caminho: str) -> int:
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with io.open(caminho, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUNAS, lineterminator="\n")
        w.writeheader()
        for r in sorted(resultados, key=lambda x: (x.ciclo, chave(x.alimento))):
            w.writerow(asdict(r))
    return len(resultados)


def ler_csv(caminho: str) -> Sequence[Resultado]:
    with io.open(caminho, encoding="utf-8") as fh:
        return tuple(Resultado(ciclo=int(l["ciclo"]), alimento=l["alimento"],
                               n_amostras=int(l["n_amostras"]),
                               n_insatisfatorias=int(l["n_insatisfatorias"]))
                     for l in csv.DictReader(fh))


# ─────────────────────────── linha de comando ───────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Extrai o resultado por alimento do PARA.")
    p.add_argument("pdf", help="relatório do ciclo, em PDF, baixado da Anvisa")
    p.add_argument("--ciclo", type=int, default=2024)
    p.add_argument("-o", "--saida", default=None,
                   help="CSV curado (padrão: dados/para_<ciclo>.csv)")
    args = p.parse_args(argv)
    saida = args.saida or os.path.join("dados", "para_%d.csv" % args.ciclo)

    resultados, faltaram = extrair(ler_pdf(args.pdf), args.ciclo)
    ok, msg = valida(resultados, args.ciclo, faltaram)
    print("VALIDAÇÃO: %s" % msg)
    if not ok:
        print("A extração não confere com o relatório. Nada foi gravado.")
        return 1

    # Se já existe tabela curada, a extração precisa reproduzi-la. É o que impede
    # uma mudança de diagramação do PDF de reescrever silenciosamente o dado.
    if os.path.exists(saida):
        antigo = {(r.ciclo, chave(r.alimento)): r for r in ler_csv(saida)}
        novo = {(r.ciclo, chave(r.alimento)): r for r in resultados}
        if antigo and antigo != {k: v for k, v in novo.items() if k in antigo}:
            print("DIVERGE do que está gravado em %s — nada foi escrito." % saida)
            for k in sorted(set(antigo) | set(novo)):
                if antigo.get(k) != novo.get(k):
                    print("   %s: gravado=%s  extraído=%s"
                          % (k[1], antigo.get(k), novo.get(k)))
            return 1

    gravar(resultados, saida)
    print("%d alimentos gravados em %s" % (len(resultados), saida))
    print()

    print("%-11s %6s %6s %8s   %-17s  %s"
          % ("alimento", "n", "insat", "%", "IC 90%", "cobertura da meta"))
    print("-" * 78)
    for r in sorted(resultados, key=lambda x: -x.pct_insatisfatorio):
        lo, hi = wilson(r.n_insatisfatorias, r.n_amostras)
        cob = 100.0 * r.n_amostras / cat.ANVISA_PARA.meta_amostral
        marca = "" if cob >= 100 else "  <- abaixo"
        print("%-11s %6d %6d %7.1f%%   %5.1f%% – %5.1f%%   %5.0f%%%s"
              % (r.alimento, r.n_amostras, r.n_insatisfatorias,
                 r.pct_insatisfatorio, lo, hi, cob, marca))
    return 0


if __name__ == "__main__":
    sys.exit(main())
