# -*- coding: utf-8 -*-
"""
Ingestão da aquisição alimentar domiciliar (POF, tabela 2393 do SIDRA).

Lê a tabela bruta, aplica a classificação NOVA e grava a participação calórica por
grupo, em três níveis: Brasil, grandes regiões e unidades da federação.

SEPARAÇÃO ENTRE TRANSFORMAR E LER/GRAVAR
    As funções que calculam recebem e devolvem DataFrame; só `ler_tabela_2393` e
    `gravar` tocam disco. É o que permite testar o cálculo com uma tabelinha de
    seis linhas, sem os 1,9 GB de microdados e sem baixar nada do IBGE.

    Este módulo não importa Streamlit. A camada de visualização lê o Parquet que
    ele grava; nunca o contrário.

O QUE ENTRA NO CÁLCULO
    Só produtos folha — categorias de três níveis, como "1.1.2 Arroz polido". As
    linhas de grupo ("1. Cereais e leguminosas", "1.1 Cereais") são somatórios da
    própria tabela; incluí-las contaria o mesmo alimento duas vezes.

CONVENÇÃO DE ARREDONDAMENTO
    `pct_calorias` é arredondado a uma casa só no fim, sobre a razão exata. Somar
    componentes já arredondados dá resultado diferente do total exato em cerca de
    uma célula em quatro, e foi assim que 40 células do painel divergiram do SIDRA
    até setembro de 2026.
"""
import unicodedata

import pandas as pd

from painel_san.modulos.san import nova

REGIOES = ["Norte", "Nordeste", "Sudeste", "Sul", "Centro-Oeste"]
ENCODINGS = ("utf-8-sig", "utf-8", "latin1")

COLUNAS_MINIMAS = {"categoria_1", "localidade_nome", "periodo", "valor"}


def ler_tabela_2393(caminho):
    """Lê a tabela 2393 exportada do SIDRA, resolvendo o encoding por tentativa.

    O IBGE exporta ora em UTF-8 com BOM, ora em latin-1. Ler com o encoding errado
    não levanta erro: produz "AquisiÃ§Ã£o" no lugar de "Aquisição", e a partir daí
    nenhuma palavra-chave casa. A heurística procura esse "Ã" na amostra.
    """
    ultimo = None
    for enc in ENCODINGS:
        try:
            df = pd.read_csv(caminho, dtype=str, encoding=enc)
        except (UnicodeDecodeError, ValueError) as e:
            ultimo = e
            continue
        amostra = " ".join(df["categoria_1"].dropna().head(30).tolist())
        if "Ã" not in amostra:
            return df
        ultimo = "encoding %s produziu mojibake" % enc
    raise ValueError("não consegui ler %s: %s" % (caminho, ultimo))


def preparar(df):
    """Normaliza os nomes, converte `valor` para número e descarta linhas sem valor.

    A normalização NFC importa: o SIDRA mistura "ç" como caractere único e como
    "c" + cedilha combinante, e as duas formas não são iguais para o `in` do
    Python, o que faria a mesma categoria classificar diferente conforme a linha.
    """
    faltando = COLUNAS_MINIMAS - set(df.columns)
    if faltando:
        raise ValueError("colunas ausentes na tabela: %s" % sorted(faltando))
    df = df.copy()
    df["categoria_1"] = df["categoria_1"].apply(
        lambda s: unicodedata.normalize("NFC", str(s).strip()))
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    return df.dropna(subset=["valor"])


def classificar(df):
    """Acrescenta nova_grupo, kcal_por_100g e kcal_pc_ano.

    `kcal_pc_ano = valor (kg/ano per capita) × kcal/100 g × 10`.

    Atenção ao kcal zero: ele não coloca o alimento no grupo errado, ele o faz
    somar zero no numerador E no denominador, ou seja, sumir do cálculo sem erro
    nenhum. `nova.py` tem teste para isso.
    """
    df = df.copy()
    tabela = {p: nova.classificar_produto(p) for p in df["categoria_1"].unique()}
    df["nova_grupo"] = df["categoria_1"].map(lambda p: tabela[p][0])
    df["kcal_por_100g"] = df["categoria_1"].map(lambda p: tabela[p][1])
    df["nova_grupo"] = pd.to_numeric(df["nova_grupo"], errors="coerce")
    df["kcal_por_100g"] = pd.to_numeric(df["kcal_por_100g"], errors="coerce")
    df["kcal_pc_ano"] = df["valor"] * df["kcal_por_100g"] * 10
    return df


def apenas_folhas(df):
    """Descarta as linhas de grupo, que são somatórios da própria tabela."""
    return df[df["nova_grupo"].notna()
              & df["kcal_pc_ano"].notna()
              & df["categoria_1"].apply(nova.is_produto_folha)].copy()


def participacao_calorica(df, chaves):
    """Participação de cada grupo NOVA no total de calorias, por `chaves`.

    `chaves` é a lista de colunas que define o recorte: ["periodo"] para o Brasil,
    ["localidade_nome", "periodo"] para região ou UF.
    """
    df = df.copy()
    df["nova_grupo"] = df["nova_grupo"].astype(int)
    total = (df.groupby(chaves)["kcal_pc_ano"].sum().reset_index()
             .rename(columns={"kcal_pc_ano": "kcal_total"}))
    por_grupo = (df.groupby(chaves + ["nova_grupo"])["kcal_pc_ano"].sum().reset_index()
                 .rename(columns={"kcal_pc_ano": "kcal_nova"}))
    saida = por_grupo.merge(total, on=chaves)
    saida["pct_calorias"] = (saida["kcal_nova"] / saida["kcal_total"] * 100).round(1)
    saida["nova_rotulo"] = saida["nova_grupo"].map(nova.NOVA_ROTULOS)
    return saida.sort_values(chaves + ["nova_grupo"]).reset_index(drop=True)


def agregar(df_folhas):
    """Devolve {"brasil": df, "regiao": df, "uf": df}.

    Os três níveis convivem na mesma tabela do SIDRA, na coluna `localidade_nome`,
    e precisam ser separados antes de agregar — senão o Brasil entra na soma das
    regiões e cada alimento é contado três vezes.
    """
    localidades = set(df_folhas["localidade_nome"].unique())
    ufs = sorted(localidades - {"Brasil"} - set(REGIOES))
    return {
        "brasil": participacao_calorica(
            df_folhas[df_folhas["localidade_nome"] == "Brasil"], ["periodo"]),
        "regiao": participacao_calorica(
            df_folhas[df_folhas["localidade_nome"].isin(REGIOES)],
            ["localidade_nome", "periodo"]),
        "uf": participacao_calorica(
            df_folhas[df_folhas["localidade_nome"].isin(ufs)],
            ["localidade_nome", "periodo"]),
    }


def mapa_classificacao(df):
    """Mapeamento auditável produto → grupo, para conferência humana.

    É o artefato que um revisor abre para checar a classificação item a item, e o
    que revelou, em setembro de 2026, que "Salgadinho" estava em NOVA 2 com kcal
    zero. Vale mais que o agregado.
    """
    cols = ["categoria_1", "nova_grupo", "kcal_por_100g"]
    saida = df[cols].drop_duplicates().copy()
    saida["nova_rotulo"] = saida["nova_grupo"].map(nova.NOVA_ROTULOS)
    return saida.sort_values(["nova_grupo", "categoria_1"]).reset_index(drop=True)


def processar(caminho_tabela):
    """Da tabela bruta aos quatro quadros prontos para gravar."""
    df = classificar(preparar(ler_tabela_2393(caminho_tabela)))
    saida = agregar(apenas_folhas(df))
    # O mapa sai da tabela INTEIRA, não só das folhas: as linhas de grupo não
    # entram no cálculo, mas quem confere a classificação quer vê-las também.
    saida["mapa"] = mapa_classificacao(df)
    return saida


def gravar(quadros, destino):
    """Grava cada quadro como Parquet em `destino`, devolvendo os caminhos.

    Parquet, e não CSV, porque preserva tipo. Com CSV o separador decimal vira
    questão de configuração regional, e este projeto já perdeu tempo com número
    lido como texto por causa de vírgula.
    """
    from pathlib import Path
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    escritos = {}
    for nome, quadro in quadros.items():
        caminho = destino / ("nova_%s.parquet" % nome)
        quadro.to_parquet(caminho, index=False)
        escritos[nome] = caminho
    return escritos


def main(argv=None):
    import argparse
    from pathlib import Path

    p = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    p.add_argument("tabela", type=Path,
                   help="CSV da tabela 2393 exportado do SIDRA")
    p.add_argument("-o", "--destino", type=Path, default=Path("dados/processado"),
                   help="pasta de saída (padrão: dados/processado)")
    args = p.parse_args(argv)

    quadros = processar(args.tabela)
    escritos = gravar(quadros, args.destino)
    for nome, caminho in escritos.items():
        print("%-8s %5d linhas  ->  %s" % (nome, len(quadros[nome]), caminho))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
