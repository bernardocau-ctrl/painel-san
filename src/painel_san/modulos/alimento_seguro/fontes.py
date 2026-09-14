# -*- coding: utf-8 -*-
"""
Catálogo das fontes de vigilância de alimento seguro.

ESTE ARQUIVO É A CONTRIBUIÇÃO, NÃO A INFRAESTRUTURA
    Um módulo de dados comum teria aqui uma lista de URLs. Este catálogo carrega,
    para cada fonte, **a régua e a origem da régua** — com que periodicidade o
    próprio órgão se comprometeu a medir, e em que documento ele disse isso.

    A distinção importa porque o projeto inteiro depende dela. Dizer que o PARA
    está atrasado é opinião; dizer que ele mede cada alimento uma vez por ciclo
    de três anos, conforme o Plano Plurianual que a própria Anvisa publicou, é
    fato verificável. Nunca inventamos o padrão: cobramos de cada órgão o que ele
    declarou.

    Por isso todo campo de régua vem acompanhado de `regua_fonte`, que aponta o
    documento, e de `regua_verificada`, que diz se alguém conferiu no primário.
    Régua não verificada não deve sustentar afirmação pública.

SOBRE AS DIMENSÕES SEREM INDEPENDENTES
    Uma fonte pode estar em dia e ainda assim ser inútil. O PARA do ciclo 2024 é
    atual e ilegível por máquina ao mesmo tempo, e em seis dos catorze alimentos
    ficou abaixo da meta amostral que a própria Anvisa declarou. Três falhas
    distintas, com remédios distintos.

    Por isso o catálogo não tem um campo "situação". Quem avalia é `latencia.py`,
    e devolve uma dimensão de cada vez.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple


# ─────────────────────────── vocabulário ───────────────────────────
class Formato:
    """Legibilidade por máquina, que é o que interessa aqui.

    XLSX conta como legível: é chato, mas é parseável sem heurística. PDF não —
    extrair dele exige inferir estrutura a partir de posição no papel, e o
    resultado precisa ser validado contra algum total publicado.
    """
    CSV = "CSV"
    JSON = "JSON"
    XLSX = "XLSX"
    PARQUET = "PARQUET"
    PDF = "PDF"
    HTML = "HTML"

    LEGIVEIS = frozenset({CSV, JSON, XLSX, PARQUET})


# Periodicidade contínua: a fonte é um registro, atualizado quando há ato novo,
# e não uma medição com calendário. Não faz sentido calcular atraso.
PERIODICIDADE_CONTINUA = None


@dataclass(frozen=True)
class Fonte:
    """Uma fonte pública de dado de vigilância, com a régua que ela mesma declarou."""

    id: str
    nome: str
    orgao: str
    url: str
    formato: str

    # A promessa, e de onde ela vem.
    periodicidade_meses: Optional[int]
    regua_fonte: str
    regua_verificada: bool = False

    # Quantos dias de atraso toleramos antes de chamar de atraso.
    #
    # Era uma constante única de 15% do prazo, e estava invertida: 15% de 36
    # meses dá cinco meses e meio de perdão ao PARA, enquanto 15% de 3 meses dá
    # catorze dias ao SISAGUA. A fonte mais lenta ganhava doze vezes mais folga
    # absoluta que a mais rápida — o contrário do que se queria.
    #
    # ATENÇÃO: diferente de todo o resto deste arquivo, este número é NOSSO, não
    # do órgão. Nenhum deles declara tolerância. Por isso `regua_tolerancia` diz
    # explicitamente que a escolha é nossa e por quê: quem discordar precisa
    # poder discordar do número certo, e não do instrumento inteiro.
    tolerancia_dias: Optional[int] = None
    regua_tolerancia: str = ""

    # A URL acima devolve o DADO, ou só a página onde ele mora?
    #
    # Descoberto na primeira rodada do registrador, em 14/09/2026: três das cinco
    # fontes respondem text/html, porque não existe endereço estável que entregue
    # o arquivo corrente. No IBAMA, uma URL fixa sempre devolve o CSV atualizado.
    # No PARA, cada relatório tem um identificador numérico opaco e não há índice
    # legível — para saber o que há de novo, é preciso um humano abrir a página.
    #
    # Isso é uma falha de legibilidade mais profunda que o formato do arquivo:
    # nem a descoberta do dado é automatizável. E é distinta de "o arquivo é PDF",
    # porque tem outro remédio — publicar um índice resolve uma, converter o
    # arquivo resolve a outra.
    endpoint_estavel: bool = True

    # Em que eixos o dado pode ser desagregado. Pedir recorte fora desta tupla
    # não é lacuna de medição: é limite de granularidade, que é outra falha.
    granularidade: Tuple[str, ...] = ()

    # META amostral que o próprio órgão declarou para o ciclo, quando declarou.
    #
    # Chamava-se `minimo_amostral`, e a palavra carregava uma conclusão que não
    # nos cabe. As 231 amostras do PARA são a meta que a Anvisa calculou para
    # aquele desenho e aquele ciclo — não um limiar universal de
    # representatividade. Uma coisa é dizer "ficou em 37% da meta declarada,
    # calculada assim, nesta página"; outra é dizer "a amostra é insuficiente",
    # que é afirmação estatística sobre o país e exigiria conhecer população-alvo,
    # desenho probabilístico, perdas e desfecho.
    #
    # A primeira é verificável. A segunda é nossa opinião com cara de número.
    meta_amostral: Optional[int] = None
    regua_meta: Optional[str] = None

    observacao: str = ""

    @property
    def legivel(self) -> bool:
        return self.formato in Formato.LEGIVEIS

    @property
    def tem_calendario(self) -> bool:
        return self.periodicidade_meses is not None

    def desagrega_por(self, eixo: str) -> bool:
        return eixo in self.granularidade


# ─────────────────────────── o catálogo ───────────────────────────
IBAMA_COMERCIALIZACAO = Fonte(
    id="ibama_comercializacao",
    nome="Relatórios de comercialização de agrotóxicos",
    orgao="IBAMA",
    url=("https://stibamadadosabertosprd.blob.core.windows.net/dados-abertos/dados/"
         "AGROTOXICOS/RelatoriosdeComercializacaodeAgrotoxicos/"
         "relatorios_comercializacao_agrotoxicos.csv"),
    formato=Formato.CSV,
    periodicidade_meses=6,
    regua_fonte=("Art. 41 do Decreto 4.074/2002: empresas entregam dados 'até 31 de "
                 "janeiro e 31 de julho de cada ano', conforme o Anexo VII. É a régua "
                 "que o próprio IBAMA publica hoje na página do Relatório Semestral. "
                 "RESSALVA: há indício de que o Decreto 10.833/2021 mudou esse artigo "
                 "para anual — ver observação."),
    regua_verificada=False,   # ver observação: tentativa de 14/09/2026 não concluiu
    tolerancia_dias=60,
    regua_tolerancia=("Escolha nossa. Dois meses sobre um ciclo de seis: consolidar "
                      "declaração de empresa leva tempo, e o CSV é cumulativo."),
    granularidade=("uf", "semestre", "ingrediente_ativo", "classe_de_uso"),
    observacao=(
        "RÉGUA EM DISPUTA — tentativa de verificação em 14/09/2026, não concluída.\n\n"
        "Duas versões do art. 41 do Decreto 4.074/2002 circulam:\n"
        "  · a página do próprio IBAMA, hoje, diz semestral, 31/01 e 31/07, "
        "citando o art. 41 e o Anexo VII;\n"
        "  · fontes secundárias afirmam que o Decreto 10.833/2021 alterou esse "
        "artigo para ANUAL, até 31 de janeiro.\n\n"
        "O texto consolidado no Planalto recusou conexão em três tentativas, e a "
        "cópia do decreto que o MAPA publica é anterior a 2021 (tem dezesseis "
        "anotações de redação, nenhuma daquele ano). A Câmara devolveu 429.\n\n"
        "Mantemos SEIS MESES porque a régua emprestada é a que o órgão declara de "
        "si hoje, e o IBAMA declara semestral na sua própria página. Se a alteração "
        "de 2021 se confirmar, o achado não é que erramos — é que o IBAMA está "
        "publicando como vigente uma regra superada, o que é, ele próprio, uma "
        "falha de legibilidade da fonte.\n\n"
        "Para fechar: art. 41 do Decreto 4.074/2002 na redação consolidada, e o art. "
        "correspondente do Decreto 10.833/2021.\n\n"
        "Venda por UF é onde o produto foi COMERCIALIZADO, não onde foi aplicado nem "
        "onde o alimento foi consumido. Distribuidoras concentram venda em alguns "
        "estados."),
)

ANVISA_MONOGRAFIAS = Fonte(
    id="anvisa_monografias",
    nome="Monografias de agrotóxicos — limites máximos de resíduo",
    orgao="ANVISA",
    url="https://dados.anvisa.gov.br/dados/TA_MONOGRAFIA_AGROTOXICO.csv",
    formato=Formato.CSV,
    periodicidade_meses=PERIODICIDADE_CONTINUA,
    regua_fonte="Registro atualizado a cada ato normativo; sem calendário de medição",
    regua_verificada=True,    # o CSV traz DT_ATUALIZACAO por linha
    granularidade=("ingrediente_ativo", "cultura", "ato_legal"),
    observacao=("Traz DT_INICIO_VIGENCIA e DT_FIM_VIGENCIA, o que permite mostrar "
                "quais LMR foram afrouxados ou apertados, e em que ato."),
)

ANVISA_PARA = Fonte(
    id="anvisa_para",
    nome="Programa de Análise de Resíduos de Agrotóxicos em Alimentos (PARA)",
    orgao="ANVISA",
    url=("https://www.gov.br/anvisa/pt-br/assuntos/agrotoxicos/"
         "programa-de-analise-de-residuos-em-alimentos/relatorios-do-programa"),
    formato=Formato.PDF,
    endpoint_estavel=False,
    periodicidade_meses=36,
    regua_fonte="Plano Plurianual 2023-2025 do PARA, Tabela 1",
    regua_verificada=True,    # lido no relatório do ciclo 2024, p. 29
    tolerancia_dias=180,
    regua_tolerancia=("Escolha nossa. Seis meses sobre um ciclo de trinta e seis: o "
                      "relatório de um ciclo sai bem depois do fim das coletas, e "
                      "cobrar no dia seguinte ao fechamento seria cobrar o "
                      "impossível. É a maior tolerância do catálogo — e é de fato um "
                      "pouco mais frouxa que os 15% antigos (164 dias). A correção "
                      "não foi apertar o PARA: foi parar de dar ao SISAGUA catorze "
                      "dias só porque o prazo dele é curto."),
    granularidade=("alimento", "ciclo"),
    meta_amostral=231,
    regua_meta=("Distribuição binomial, 1% de incidência esperada acima do LOQ, "
                "IC de 90% — relatório PARA ciclo 2024, p. 30. Meta por alimento "
                "por ciclo, no desenho daquele ciclo."),
    observacao=("Nem o arquivo que a Anvisa chama de 'Dados Brutos' é planilha: "
                "responde com content-type application/pdf. Os relatórios recentes "
                "não desagregam por UF."),
)

MS_SISAGUA_AGROTOXICOS = Fonte(
    id="ms_sisagua_agrotoxicos",
    nome="SISAGUA — parâmetro agrotóxicos na água para consumo humano",
    orgao="Ministério da Saúde",
    url="https://dados.gov.br/dados/busca?termo=sisagua",
    formato=Formato.CSV,
    endpoint_estavel=False,
    periodicidade_meses=6,
    regua_fonte=("Anexo 13 do Anexo XX da Portaria de Consolidação nº 5/2017, linha "
                 "'Demais parâmetros', nota (8): agrotóxicos são monitorados na saída "
                 "do tratamento com 1 amostra SEMESTRAL, em manancial superficial ou "
                 "subterrâneo. Redação vigente dada pela Portaria GM/MS nº 2.472, de "
                 "28/09/2021 — que alterou a tabela introduzida pela 888/2021. "
                 "Art. 42 exige, em paralelo, uma amostra semestral da água bruta em "
                 "cada ponto de captação, incluindo os parâmetros de agrotóxicos."),
    regua_verificada=True,    # lido no Anexo XX, tabela do Anexo 13 e notas (8) e (9)
    tolerancia_dias=60,
    regua_tolerancia=("Escolha nossa. Dois meses sobre um ciclo de seis, a mesma do "
                      "IBAMA por ter a mesma periodicidade — e aqui a coleta é "
                      "municipal e descentralizada, com digitação posterior no "
                      "sistema nacional."),
    granularidade=("municipio", "parametro", "semestre"),
    observacao=(
        "CORREÇÃO DE 14/09/2026. O catálogo dizia 'trimestral obrigatório, Portaria "
        "888/2021', vindo de reportagem. A leitura do primário desmentiu em três "
        "pontos: a frequência de base é SEMESTRAL, não trimestral; o trimestre é "
        "regime de ESCALADA, não regra geral; e a tabela em vigor foi dada pela "
        "Portaria 2.472/2021, não pela 888.\n\n"
        "A nota (9) do Anexo 13 diz: 'Quando o parâmetro for detectado na saída do "
        "tratamento, deve-se monitorar com frequência trimestral na saída do "
        "tratamento e no sistema de distribuição.'\n\n"
        "Isso inverte a leitura do dado, e é o achado mais útil desta fonte: um "
        "sistema que aparece medindo trimestralmente é um sistema onde agrotóxico "
        "FOI detectado. A frequência, aqui, é ela própria um indicador — e ler "
        "trimestre como 'bom aluno' seria ler ao contrário.\n\n"
        "Quem mede também não é o Ministério: o art. 44 põe a obrigação nos "
        "responsáveis por SAA e SAC, que submetem plano de amostragem anual à "
        "autoridade municipal de saúde. O Ministério opera o registro. Cobrar do "
        "órgão errado é o tipo de erro que desqualifica o instrumento inteiro.\n\n"
        "O registro do parâmetro agrotóxico parou em janeiro de 2023, por falha "
        "técnica do sistema."),
)

MAPA_PNCRC = Fonte(
    id="mapa_pncrc",
    nome="Plano Nacional de Controle de Resíduos e Contaminantes",
    orgao="MAPA",
    url=("https://www.gov.br/agricultura/pt-br/assuntos/inspecao/produtos-animal/"
         "plano-de-nacional-de-controle-de-residuos-e-contaminantes"),
    formato=Formato.PDF,
    endpoint_estavel=False,
    periodicidade_meses=12,
    regua_fonte=("Planos ANUAIS DE AMOSTRAGEM do MAPA — é promessa de MEDIR, não de "
                 "publicar. Nenhum compromisso de divulgação periódica dos resultados "
                 "foi localizado até 14/09/2026. Documento a ler: Portaria SDA/MAPA "
                 "nº 1.266, de 16/04/2025, hoje a base do programa."),
    regua_verificada=False,   # o manual do MAPA na wikisda não abriu; ver observação
    tolerancia_dias=90,
    regua_tolerancia=("Escolha nossa. Um trimestre sobre um plano anual, pela mesma "
                      "razão do PARA: o relatório de um ano não sai em janeiro."),
    granularidade=("cadeia_produtiva", "ano"),
    observacao=(
        "A DISTINÇÃO QUE FALTA AQUI É A MESMA DO MÓDULO INTEIRO.\n\n"
        "O que o MAPA declara é um plano anual de AMOSTRAGEM. Isso é compromisso de "
        "medir. Não se localizou, em 14/09/2026, nenhum compromisso de PUBLICAR "
        "resultados com periodicidade definida — e as duas coisas não se deduzem uma "
        "da outra.\n\n"
        "Consequência prática: a periodicidade de doze meses aqui é a régua da "
        "medição, e usá-la para cobrar publicação é comparar compromissos diferentes. "
        "Enquanto isso não for resolvido, a avaliação temporal desta fonte deve ser "
        "lida com a confiança que ela declara, que é a mais baixa do catálogo.\n\n"
        "Cobre produtos de origem animal — carne, leite, ovos, mel — onde o PARA cobre "
        "vegetal. Dois ministérios, dois desenhos, o mesmo problema. Recorte 2007-2018 "
        "curado na Base dos Dados."),
)

CATALOGO = (
    IBAMA_COMERCIALIZACAO,
    ANVISA_MONOGRAFIAS,
    ANVISA_PARA,
    MS_SISAGUA_AGROTOXICOS,
    MAPA_PNCRC,
)


def por_id(identificador: str) -> Fonte:
    for f in CATALOGO:
        if f.id == identificador:
            return f
    raise KeyError("fonte desconhecida: %r" % identificador)


# ─────────────────────────── cronograma do PARA ───────────────────────────
# Tabela 1 do relatório do ciclo 2024: os 36 alimentos do Plano Plurianual
# 2023-2025 e o ciclo em que cada um é medido. Somam 80% da aquisição per capita.
#
# Existe por uma razão de método: sem ele, "não há morango em 2024" seria lido
# como lacuna. É ausência PLANEJADA — o morango está marcado para 2025. Confundir
# as duas destrói a credibilidade do instrumento no primeiro leitor que conhecer
# o plano.
PARA_CRONOGRAMA = {
    "abacaxi": (2023,), "abobrinha": (2024,), "alface": (2023,), "alho": (2023,),
    "amendoim": (2025,), "arroz": (2023,), "aveia": (2024,), "banana": (2024,),
    "batata": (2025,), "batata doce": (2023,), "beterraba": (2023,),
    "brocolis": (2025,), "cafe": (2025,), "cebola": (2024,), "cenoura": (2023,),
    "chuchu": (2023,), "laranja": (2023, 2024, 2025), "couve": (2024,),
    "feijao": (2025,), "goiaba": (2023,), "maca": (2024,), "mamao": (2024,),
    "mandioca": (2025,), "manga": (2023,), "maracuja": (2025,), "milho": (2024,),
    "morango": (2025,), "pepino": (2024,), "pera": (2024,), "pimentao": (2023,),
    "quiabo": (2025,), "repolho": (2025,), "soja": (2024,), "tomate": (2023,),
    "trigo": (2024,), "uva": (2023, 2024),
}
