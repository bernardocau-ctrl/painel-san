# -*- coding: utf-8 -*-
"""
Registrador: observa periodicamente o estado das fontes e acumula histórico.

POR QUE ISTO EXISTE
    Sem ele, o instrumento é uma fotografia: "hoje o SISAGUA está atrasado". Com
    ele, vira série: "o SISAGUA está atrasado há N meses, e a distância está
    aumentando". A segunda afirmação é a que ninguém pode fazer hoje, porque
    ninguém guardou a medição.

    Cada execução é uma observação com carimbo de tempo. O valor não está em
    nenhuma linha isolada — está no acúmulo. Por isso o custo de não começar é
    alto e não se recupera: um mês que passou sem registro é um ponto que não
    existe mais.

O QUE É OBSERVADO
    O que o servidor diz sobre o arquivo, sem baixá-lo: status HTTP, tipo de
    conteúdo, tamanho, e a data de última modificação que ele declara. É pouco, e
    é suficiente — o objetivo não é o dado, é saber se o dado está lá, em que
    formato e desde quando.

    Baixar 13,5 MB do IBAMA todo mês seria desperdício e deselegante com o
    servidor público. `HEAD` resolve; quando o servidor não aceita `HEAD`, cai
    para um `GET` de um byte.

POR QUE CSV, E NÃO PARQUET
    Contraria a escolha do módulo SAN, e de propósito. Este arquivo é um registro
    append-only, commitado a cada execução. Em CSV, o git mostra a linha nova no
    diff; em Parquet, cada commit reescreve um blob binário e o histórico fica
    ilegível.

    Aqui a diffabilidade é o produto: o histórico de commits do registro **é** a
    evidência de que a medição foi contínua e não foi retroalimentada.

FALHA NÃO É EXCEÇÃO, É OBSERVAÇÃO
    Fonte fora do ar, timeout, 404 — nada disso interrompe a execução nem é
    tratado como erro do programa. É exatamente o que se quer registrar. Uma
    rodada em que uma fonte some é uma rodada bem-sucedida com um achado.
"""
import argparse
import csv
import io
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple

from painel_san.modulos.alimento_seguro import fontes as cat
from painel_san.modulos.alimento_seguro.fontes import Fonte

# Identificar-se é boa prática ao bater repetidamente em servidor público, e
# permite que o administrador saiba quem está consultando e por quê.
AGENTE = ("painel-san/0.1 (observatorio de disponibilidade de dados de vigilancia; "
          "https://github.com/bernardocau-ctrl/painel-san)")

TIMEOUT = 30

# `etag` entrou depois da primeira rodada. É o único identificador de versão que
# alguns servidores oferecem e o `last-modified` não cobre: o IBAMA republica o
# CSV cumulativo sem mexer na data declarada, e nesse caso a troca do etag é a
# ÚNICA pista de que o arquivo mudou. Custa zero — vem no mesmo cabeçalho que já
# se lê — e sem ele a série registraria "nada mudou" numa rodada em que mudou.
#
# Acrescentar coluna a um arquivo append-only exige reescrever o cabeçalho e
# completar as linhas antigas com campo vazio. Feito uma vez, em 14/09/2026,
# preservando as cinco observações do ponto zero.
COLUNAS = ("carimbo", "fonte_id", "url", "metodo", "http_status", "content_type",
           "content_length", "last_modified", "etag", "erro")


@dataclass(frozen=True)
class Registro:
    """Uma observação de uma fonte, num instante."""
    carimbo: str
    fonte_id: str
    url: str
    metodo: str
    http_status: Optional[int]
    content_type: str
    content_length: Optional[int]
    last_modified: str
    etag: str
    erro: str

    @property
    def respondeu(self) -> bool:
        return self.http_status is not None and 200 <= self.http_status < 300


# ─────────────────────────── observação ───────────────────────────
def _cabecalhos(resposta) -> dict:
    return {k.lower(): v for k, v in resposta.headers.items()}


def consultar(url: str, timeout: int = TIMEOUT) -> Tuple[str, Optional[int], dict, str]:
    """Bate na URL e devolve (método usado, status, cabeçalhos, erro).

    Tenta `HEAD` primeiro. Servidores que não o implementam costumam responder
    405; nesses casos cai para um `GET` pedindo um único byte, que é o mínimo
    necessário para ver os cabeçalhos sem transferir o arquivo.
    """
    for metodo in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=metodo)
        req.add_header("User-Agent", AGENTE)
        if metodo == "GET":
            req.add_header("Range", "bytes=0-0")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return metodo, r.status, _cabecalhos(r), ""
        except urllib.error.HTTPError as e:
            if metodo == "HEAD" and e.code in (403, 405, 501):
                continue                      # servidor não aceita HEAD; tenta GET
            return metodo, e.code, _cabecalhos(e), ""
        except Exception as e:                # rede, DNS, timeout, TLS
            if metodo == "HEAD":
                continue
            return metodo, None, {}, "%s: %s" % (type(e).__name__, e)
    return "GET", None, {}, "sem resposta"


def observar(fonte: Fonte, agora: Optional[datetime] = None,
             timeout: int = TIMEOUT) -> Registro:
    """Observa uma fonte. Nunca levanta: falha de rede vira campo `erro`."""
    agora = agora or datetime.now(timezone.utc)
    metodo, status, cab, erro = consultar(fonte.url, timeout)
    tamanho = cab.get("content-length")
    return Registro(
        carimbo=agora.isoformat(timespec="seconds"),
        fonte_id=fonte.id,
        url=fonte.url,
        metodo=metodo,
        http_status=status,
        content_type=(cab.get("content-type") or "").split(";")[0].strip(),
        content_length=int(tamanho) if tamanho and tamanho.isdigit() else None,
        last_modified=cab.get("last-modified", ""),
        etag=cab.get("etag", "").strip('"'),
        erro=erro,
    )


# ─────────────────────────── interpretação ───────────────────────────
# O que cada formato declarado no catálogo deve produzir como content-type.
# `octet-stream` aparece muito: é o que servidores devolvem quando não sabem
# dizer, e não prova nada — por isso aceita qualquer formato.
ESPERADO = {
    cat.Formato.CSV: ("text/csv", "application/csv", "application/octet-stream"),
    cat.Formato.JSON: ("application/json", "text/json", "application/octet-stream"),
    cat.Formato.XLSX: ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       "application/octet-stream"),
    cat.Formato.PDF: ("application/pdf", "application/octet-stream"),
    cat.Formato.HTML: ("text/html",),
}


def divergencias(fonte: Fonte, reg: Registro) -> Tuple[str, ...]:
    """O que mudou em relação ao que o catálogo afirma.

    Este é o coração do registrador: uma divergência aqui **é a notícia**. Se o
    PARA um dia responder `text/csv`, a Anvisa passou a publicar em formato
    aberto — e o instrumento precisa avisar, não engolir.
    """
    fora = []
    if reg.erro:
        fora.append("fonte inacessível: %s" % reg.erro)
        return tuple(fora)
    if not reg.respondeu:
        fora.append("HTTP %s" % reg.http_status)
        return tuple(fora)
    if reg.content_length == 0:
        fora.append("respondeu 200 com corpo vazio")

    if not fonte.endpoint_estavel:
        # A URL é a página onde o dado mora, não o dado. Responder text/html é o
        # esperado, e cobrá-la de devolver PDF seria falso positivo. A ausência
        # de endpoint já está registrada no catálogo, e é achado por si — mas é
        # achado permanente, não novidade de cada rodada.
        return tuple(fora)

    aceitos = ESPERADO.get(fonte.formato, ())
    if reg.content_type and aceitos and reg.content_type not in aceitos:
        fora.append("catálogo diz %s, servidor respondeu %s"
                    % (fonte.formato, reg.content_type))
    return tuple(fora)


# ─────────────────────────── persistência ───────────────────────────
def acrescentar(registros: Sequence[Registro], caminho: str) -> int:
    """Anexa observações ao registro, criando o cabeçalho se o arquivo for novo.

    `newline=""` e `\\n` explícito porque o arquivo é commitado: sem isso, a
    mesma execução no Windows e no CI do Linux produziria diffs diferentes.
    """
    novo = not os.path.exists(caminho)
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with io.open(caminho, "a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUNAS, lineterminator="\n")
        if novo:
            w.writeheader()
        for r in registros:
            w.writerow({k: ("" if v is None else v) for k, v in asdict(r).items()})
    return len(registros)


def rodada(catalogo=cat.CATALOGO, agora: Optional[datetime] = None,
           timeout: int = TIMEOUT) -> Sequence[Registro]:
    """Observa todas as fontes. Uma que falhe não impede as outras."""
    return [observar(f, agora, timeout) for f in catalogo]


# ─────────────────────────── linha de comando ───────────────────────────
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("-o", "--registro", default="dados/registro_fontes.csv",
                   help="CSV append-only do histórico (padrão: dados/registro_fontes.csv)")
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    args = p.parse_args(argv)

    regs = rodada(timeout=args.timeout)
    acrescentar(regs, args.registro)

    achados = 0
    for r in regs:
        fonte = cat.por_id(r.fonte_id)
        divs = divergencias(fonte, r)
        marca = "!" if divs else " "
        print("%s %-24s HTTP %-4s %-26s %s" % (
            marca, r.fonte_id, r.http_status or "-", r.content_type or "-",
            r.last_modified or "sem last-modified"))
        for d in divs:
            achados += 1
            print("      -> %s" % d)

    print()
    print("%d observações anexadas a %s" % (len(regs), args.registro))
    if achados:
        print("%d divergência(s) em relação ao catálogo — vale olhar." % achados)
    # Divergência não é erro de execução: a rodada cumpriu seu papel ao registrá-la.
    return 0


if __name__ == "__main__":
    sys.exit(main())
