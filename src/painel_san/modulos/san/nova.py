# -*- coding: utf-8 -*-
"""
Classificação NOVA dos produtos da POF (tabela 2393 do SIDRA).

Este módulo é PURO: recebe o nome de um produto e devolve (grupo, kcal/100g).
Não lê arquivo, não escreve arquivo, não imprime, não importa Streamlit. É essa
propriedade que o torna testável sem subir nada — e é o critério que o JOSS aplica
a ferramentas web ("lack of modularity and challenges testing the code").

Baseado em:
  - Monteiro CA et al. NOVA. The star shines bright. World Nutrition, 2016.
  - Ministério da Saúde. Guia Alimentar para a População Brasileira. 2ª ed. 2014.
  - NEPA-UNICAMP. TACO 4ª ed. 2011 (valores calóricos).

COMO AS REGRAS SÃO AVALIADAS
    Na ordem NOVA 4 → 3 → 2 → 1. A primeira que casa vence, e a ordem importa:
    "Salsicha comum" contém "cha", mas cai no NOVA 4 antes de chegar à regra do chá.

    Uma regra é uma lista de palavras-chave e exige TODAS presentes (AND). Para
    variantes de acento isso equivale a OR, porque `normalizar()` as converge.
    Para sinônimos de verdade, NÃO equivale — e uma lista de sinônimos escrita
    junta nunca dispara. Cinco defeitos desse tipo viveram meses no pipeline
    (biscoito, salgadinho, aguardente, goiabada, doce de leite); veja
    `tests/test_nova.py`, que os fixa como casos.

    O casamento é por SUBSTRING, de propósito: é o que faz "Frutas" casar "fruta"
    e "Biscoitos" casar "biscoito". Trocar por fronteira de palavra () em todas
    as regras deixa 36 categorias órfãs — testado. Palavras-chave curtas exigem
    cuidado: a regra genérica ["sal"] casava dentro de "salgado" e mandava
    salgadinho para NOVA 2 com kcal zero, o que o removia do cálculo em silêncio.

QUANDO NENHUMA REGRA CASA
    `NOVA_POR_GRUPO_PAI` dá um padrão pelo número do grupo da POF. Hoje 29% dos
    produtos folha dependem desse fallback — a maioria são linhas "Outros".
"""
import re
import unicodedata

# ─────────────────────────────────────────────────────────────────────
# REGRAS DE CLASSIFICAÇÃO NOVA (por palavras-chave no nome)
# Avaliadas na ordem: NOVA 4 → NOVA 3 → NOVA 2 → NOVA 1 (default)
# ─────────────────────────────────────────────────────────────────────

# Cada regra: (lista_de_keywords, nova_grupo, kcal_padrao)
# A primeira regra que bate vence → mais específicas primeiro

REGRAS_NOVA4 = [
    # ── Bebidas industrializadas ───────────────────────────────────────
    (["refrigerante"],                        4, 38),
    (["bebida energética", "energetica"],     4, 46),
    (["suco", "envasado"],                    4, 50),   # suco envasado/caixinha
    (["suco", "pó"],                          4, 375),  # suco em pó
    (["achocolatado"],                        4, 63),
    (["leite fermentado"],                    4, 65),   # yakult/actimel
    # ── Embutidos e carnes processadas industriais ─────────────────────
    (["mortadela"],                           4, 280),
    (["salsicha"],                            4, 226),
    (["salame"],                              4, 336),
    (["presunto"],                            4, 145),
    (["linguiça"],                            4, 295),
    (["paio"],                                4, 320),
    # Sinonimos separados em 10/09/2026: bate() exige TODAS as palavras da
    # lista (AND). Escritas juntas, estas regras exigiam que o nome contivesse
    # os dois termos ao mesmo tempo e NUNCA disparavam.
    (["hambúrger"],                           4, 215),  # carne de hambúrguer
    (["hamburguer"],                          4, 215),
    (["nugget", "empanado"],                  4, 230),  # frango empanado/nuggets
    # ── Lácteos ultraprocessados ───────────────────────────────────────
    (["leite condensado"],                    4, 327),
    (["leite", "achocolatado"],               4, 63),
    (["sobremesa láctea", "sobremesa lactea"],4, 120),
    # ── Panificados e massas industriais ──────────────────────────────
    (["pão de forma", "pao de forma"],        4, 268),
    (["pão integral industrializado"],        4, 247),
    (["torrada"],                             4, 380),
    # Sinonimos separados em 10/09/2026: bate() exige TODAS as palavras da
    # lista (AND). Escritas juntas, estas regras exigiam que o nome contivesse
    # os dois termos ao mesmo tempo e NUNCA disparavam.
    (["biscoito"],                            4, 453),  # todo biscoito = NOVA 4
    (["bolacha"],                             4, 453),
    (["rosca doce"],                          4, 430),
    (["rosca salgada"],                       4, 430),
    (["bolo"],                                4, 386),
    (["macarrão instantâneo", "miojo"],       4, 430),
    (["mistura para bolo"],                   4, 378),
    # ── Gorduras e condimentos industriais ────────────────────────────
    (["margarina"],                           4, 545),
    (["maionese"],                            4, 656),
    (["ketchup"],                             4, 95),
    (["caldo", "tablete"],                    4, 320),  # caldo knorr etc.
    (["molho", "tomate"],                     4, 82),   # molho industrializado
    (["tempero misto"],                       4, 250),
    (["massa de tomate"],                     4, 68),
    # ── Snacks e lanches ──────────────────────────────────────────────
    (["batata frita"],                         4, 312),  # NOVA 4 — antes de "batata" NOVA 1
    (["frango empanado"],                      4, 230),
    (["frango assado"],                        3, 215),  # assado simples = processado
    (["carne assada"],                         3, 200),
    (["salgadinho"],                          4, 530),
    (["chips"],                               4, 530),
    (["pipoca", "industrializ"],              4, 460),
    (["chocolate em tablete"],                4, 550),  # barra chocolate
    (["bombom"],                              4, 530),
    (["sorvete"],                             4, 212),
    (["gelatina"],                            4, 62),
    (["refresco em pó", "refresco"],          4, 375),
    (["fórmula infantil", "formula infantil"],4, 500),
    # ── Alimentos prontos / congelados ────────────────────────────────
    (["alimento congelado"],                   4, 130),
    (["prato congelado"],                      4, 130),
    (["refeição pronta", "refeição"],         4, 110),
    (["sanduíche industrializado"],           4, 220),
    (["pizza congelada"],                     4, 265),
    # ── Flocos de cereais açucarados ──────────────────────────────────
    (["flocos de milho"],                     4, 380),  # corn flakes
    (["flocos de outros cereais"],            4, 370),
    (["cereal matinal"],                      4, 380),
    (["achocolatado", "pó"],                  4, 392),
    (["chocolate em pó"],                     4, 370),
]

# Corrige o formato das tuplas (alguns têm elemento extra por erro)
REGRAS_NOVA4 = [
    (r[0], r[1] if isinstance(r[1], int) else r[2], r[-1])
    for r in REGRAS_NOVA4
    if isinstance(r[0], list)
]

REGRAS_NOVA3 = [
    # ── Laticínios processados ─────────────────────────────────────────
    (["queijo"],                              3, 320),
    (["requeijão"],                           3, 239),
    (["requejiao"],                           3, 239),  # variante com erro de grafia
    (["iogurte"],                             3, 58),
    (["leite em pó"],                         3, 496),  # desidratado = processado
    (["creme de leite"],                      3, 235),
    (["manteiga"],                            2, 726),  # ingrediente culinário
    # ── Pães artesanais / padaria ──────────────────────────────────────
    (["pão francês", "pao frances"],          3, 289),
    (["pão caseiro", "pao caseiro"],          3, 260),
    (["pão de queijo"],                       3, 300),
    (["pão de milho"],                        3, 250),
    (["pão doce"],                            3, 310),
    (["pão integral"],                        3, 247),
    (["pão", "padaria"],                      3, 275),  # genérico padaria
    (["rosca"],                               3, 390),  # rosca simples
    # ── Carnes processadas (sal/defumação, sem aditivos quím.) ─────────
    (["carne de sol"],                        3, 212),
    (["carne-seca"],                          3, 212),
    (["carne seca"],                          3, 212),
    (["charque"],                             3, 212),
    (["toucinho defumado"],                   3, 518),
    (["toucinho fresco"],                     1, 518),  # fresco = NOVA 1
    (["bacon"],                               3, 540),
    (["carne salgada"],                       3, 200),
    (["costela", "salgada"],                  3, 240),
    (["pé de porco salgado"],                 3, 200),
    (["mocotó"],                              1, 150),  # fresco
    # ── Pescados processados ───────────────────────────────────────────
    (["sardinha em conserva"],                3, 212),
    (["atum em conserva"],                    3, 130),
    (["bacalhau"],                            3, 150),  # salgado/seco
    (["peixe salgado"],                       3, 150),
    (["outros pescados salgados"],            3, 150),
    # ── Vegetais processados ───────────────────────────────────────────
    (["azeitona em conserva"],                3, 115),
    (["milho verde em conserva"],             3, 57),
    (["palmito em conserva"],                 3, 30),
    # ── Bebidas fermentadas ────────────────────────────────────────────
    (["cerveja"],                             3, 43),
    (["vinho"],                               3, 70),
    # Sinonimos separados em 10/09/2026: como AND, exigia os tres termos no
    # mesmo nome e nunca disparava. "15.1.1 Aguardente de cana" caia no fallback
    # do grupo 15 e virava NOVA 1 com 30 kcal — cachaca como alimento in natura.
    (["aguardente"],                          3, 220),
    (["cachaça"],                             3, 220),
    (["cachaca"],                             3, 220),
    (["outras aguardentes"],                  3, 200),
    (["outras", "bebidas alcoólicas"],        3, 180),
    # ── Doces processados simples ─────────────────────────────────────
    (["mel de abelha", "mel"],                1, 309),  # natural = NOVA 1
    # Idem: como AND nunca disparava, e "12.2.6 Doce de fruta em pasta" caia no
    # fallback do grupo 3 (frutas), virando NOVA 1 com 60 kcal.
    (["doce de fruta em pasta"],              3, 258),
    (["goiabada"],                            3, 258),
    # Doce de leite: NOVA 3, decidido em 10/09/2026. Leite + acucar reduzido e
    # alimento integral + acucar, a definicao do grupo 3 — mesma arquitetura da
    # goiabada logo acima. Pode ser NOVA 4 quando o rotulo traz espessantes,
    # xarope de glicose ou conservantes, mas a POF registra a categoria, nao o
    # rotulo, e afirmar aditivos que o dado nao mostra seria inventar. Fica no
    # grupo 3, que e o que o nome da categoria sustenta; se houver aditivos, o
    # NOVA 4 real e um pouco maior, coerente com a nota de que estes percentuais
    # sao um PISO da exposicao. Antes disso caia no fallback do grupo 12 e virava
    # NOVA 2 com 387 kcal — acucar puro.
    (["doce a base de leite"],                3, 295),
    (["doce de leite"],                       3, 295),
    (["doce de fruta em calda"],              3, 180),
    (["doce de fruta cristalizado"],          3, 320),
    (["geleia", "geléia"],                    3, 244),
    (["rapadura"],                            2, 380),  # ingrediente culinário
    (["polpa de fruta"],                      1, 70),   # minimamente processada
]

REGRAS_NOVA2 = [
    # ── Açúcares ──────────────────────────────────────────────────────
    (["açúcar", "acucar"],                    2, 387),
    # ── Óleos e gorduras culinárias ───────────────────────────────────
    (["óleo de soja", "oleo de soja"],        2, 884),
    (["óleo de girassol"],                    2, 884),
    (["óleo de canola"],                      2, 884),
    (["óleo de milho"],                       2, 884),
    (["azeite"],                              2, 884),
    (["óleo", "não especificado"],            2, 884),
    (["banha"],                               2, 900),
    (["gordura de porco"],                    2, 900),
    # ── Sal ───────────────────────────────────────────────────────────
    (["sal grosso"],                          2, 0),
    (["sal refinado"],                        2, 0),
    # A regra generica (["sal"], 2, 0) foi REMOVIDA em 09/09/2026.
    #
    # Ela casava por SUBSTRING, sem fronteira de palavra, entao batia dentro de
    # "salgado", "salgada", "salgadinho" — e como NOVA 2 e avaliado antes de
    # NOVA 1, sequestrava produtos que nada tem de ingrediente culinario:
    #     16.1.8 Salgadinho          -> NOVA 2, 0 kcal   (era p/ ser NOVA 4)
    #     6.3.3 Biscoito salgado     -> NOVA 2, 0 kcal   (era p/ ser NOVA 3)
    #     7.5.1 Cane salgada n.e.    -> NOVA 2, 0 kcal   (era p/ ser NOVA 1/3)
    #
    # O kcal=0 tornava o defeito silencioso: como kcal_pc_ano = valor * kcal * 10,
    # o item entrava com ZERO no numerador E no denominador, ou seja, sumia do
    # calculo sem erro nenhum, em vez de aparecer no grupo errado.
    #
    # A regra era pura sobra: as duas UNICAS categorias de sal de verdade na
    # tabela 2393 sao "13.1.1 Sal grosso" e "13.1.2 Sal refinado", e ambas ja tem
    # regra propria nas duas linhas acima, avaliadas antes. Remover nao deixa
    # nenhum sal sem classificacao — conferido nas 391 categorias.
    #
    # NAO trocar por casamento com  em todas as regras: o casamento por
    # substring e o que faz os plurais funcionarem ("Frutas" casa "fruta",
    # "Biscoitos" casa "biscoito"). Um  global deixa 36 categorias orfas.
    # ── Farinhas e amidos culinárias ──────────────────────────────────
    (["farinha de trigo"],                    2, 360),
    (["farinha de mandioca"],                 2, 361),
    (["farinha de rosca"],                    2, 350),  # processado culinário
    (["farinha vitaminada"],                  2, 350),
    (["amido de milho"],                      2, 381),
    (["fécula de mandioca"],                  2, 355),
    (["fubá de milho"],                       2, 362),
    (["creme de arroz"],                      2, 350),
    (["creme de milho"],                      2, 360),
    (["fermento"],                            2, 100),
    (["vinagre"],                             2, 5),
    (["colorau"],                             2, 100),  # urucum = condimento
    (["leite de coco"],                       2, 230),  # extrato culinário
]

REGRAS_NOVA1 = [
    # ── Cereais integrais e in natura ─────────────────────────────────
    (["arroz"],                               1, 358),
    (["milho em grão"],                       1, 360),
    (["milho verde em espiga"],               1, 86),
    (["fubá"],                                1, 362),   # quando não especif. = NOVA 1
    (["flocos de aveia"],                     1, 394),
    (["tapioca"],                             1, 350),
    (["cuscuz"],                              1, 355),
    # ── Leguminosas ───────────────────────────────────────────────────
    (["feijão", "feijao"],                    1, 335),
    (["ervilha"],                             1, 286),
    (["lentilha"],                            1, 306),
    (["soja"],                                1, 385),   # grão
    (["grão-de-bico", "grao-de-bico"],        1, 360),
    # ── Massas simples (sem ovos ou com ovos) ─────────────────────────
    (["macarrão"],                            1, 358),   # sem qualificação = seco
    (["massa de lasanha"],                    1, 350),
    (["massa de pastel"],                     1, 340),
    (["massa de pizza"],                      1, 260),
    # ── Hortaliças — uma por regra ────────────────────────────────────
    (["acelga"],      1, 15), (["agriao"],     1, 22), (["alface"],    1, 11),
    (["cheiro-verde"],1, 31), (["couve"],      1, 25), (["brocolis"],  1, 25),
    (["repolho"],     1, 22), (["abobora"],    1, 26), (["abobrinha"], 1, 18),
    (["berinjela"],   1, 17), (["cebola"],     1, 37), (["chuchu"],    1, 15),
    (["jilo"],        1, 23), (["maxixe"],     1, 12), (["pepino"],    1, 10),
    (["pimentao"],    1, 28), (["quiabo"],     1, 25), (["tomate"],    1, 15),
    (["vagem"],       1, 28), (["beterraba"],  1, 39), (["cenoura"],   1, 34),
    (["inhame"],      1,105), (["cara"],       1, 98), (["mandioca"],  1,125),
    (["alho"],        1,149), (["hortalica"],  1, 25), (["hortalicas"],1, 25),
    # Batata: genérica = NOVA 1, mas "batata frita" já foi pego em NOVA 4
    (["batata"],      1, 87),
    # ── Frutas — uma por regra ────────────────────────────────────────
    (["banana"],      1, 92), (["laranja"],    1, 47), (["mamao"],     1, 40),
    (["manga"],       1, 64), (["maracuja"],   1, 68), (["melancia"],  1, 33),
    (["melao"],       1, 23), (["abacaxi"],    1, 48), (["goiaba"],    1, 54),
    (["acerola"],     1, 37), (["abacate"],    1,103), (["limao"],     1, 30),
    (["maca"],        1, 56), (["pera"],       1, 55), (["pessego"],   1, 50),
    (["uva"],         1, 69), (["ameixa"],     1, 40), (["morango"],   1, 32),
    (["caqui"],       1, 61), (["figo"],       1, 61), (["fruta"],     1, 60),
    (["tangerina"],   1, 47), (["acai"],       1, 58),
    # ── Carnes frescas ────────────────────────────────────────────────
    (["alcatra", "patinho", "filé mignon", "contrafilé",
       "lagarto", "acém", "músculo", "capa de filé",
       "chã-de-dentro", "peito bovino"],      1, 200),
    (["carne moída"],                         1, 215),
    (["carne", "bovina", "não especificada"], 1, 200),
    (["carne", "bovinas"],                    1, 200),
    (["costela"],                             1, 265),
    (["carré", "carre"],                      1, 230),
    (["lombo"],                               1, 186),
    (["pernil"],                              1, 222),
    (["porco eviscerado"],                    1, 220),
    (["carné suína", "carne suína"],          1, 215),
    (["carne de cabrito"],                     1, 190),
    (["carne de carneiro"],                    1, 190),
    (["carne de sol"],                        3, 212),   # repetido para garantir
    # ── Aves ──────────────────────────────────────────────────────────
    (["frango", "galinha", "peru", "pato", "aves"], 1, 185),
    # ── Ovos ──────────────────────────────────────────────────────────
    (["ovo"],                                 1, 143),
    # ── Pescados frescos ──────────────────────────────────────────────
    (["fresco", "peixe"],                     1, 115),
    (["congelado", "filé"],                   1, 115),
    (["camarão", "camarao"],                  1, 69),
    (["tilápia", "tilapia", "sardinha fresca",
       "parati", "tucunaré", "tambaqui", "lambari"], 1, 100),
    (["pescado"],                             1, 110),
    # ── Vísceras ──────────────────────────────────────────────────────
    (["fígado", "figado"],                    1, 131),
    (["bucho"],                               1, 100),
    (["língua", "lingua"],                    1, 150),
    (["mocotó"],                              1, 150),
    (["víscera", "viscera"],                  1, 120),
    # ── Leite fresco/pasteurizado ─────────────────────────────────────
    (["leite de vaca fresco"],                1, 61),
    (["leite de vaca pasteurizado"],          1, 61),
    (["leite de vaca"],                       1, 61),
    (["leite integral"],                      1, 61),
    (["leite desnatado"],                     1, 36),
    # ── Oleaginosas e cocos ───────────────────────────────────────────
    (["castanha", "nozes", "amendoim",
       "amêndoa", "amendoas"],                1, 580),
    (["coco-da-baía", "coco da baia"],        1, 354),
    (["açaí", "acai"],                        1, 58),
    (["frutas secas"],                        1, 287),
    # ── Condimentos naturais ──────────────────────────────────────────
    (["cheiro-verde", "cheiro verde"],        1, 31),
    (["pimenta"],                             1, 40),
    (["gengibre"],                            1, 62),
    # ── Café, chá natural ─────────────────────────────────────────────
    (["café moído", "cafe moido"],            1, 287),
    (["café em grão"],                        1, 287),
    (["café", "não especificado"],            1, 287),
    (["chá-mate", "cha-mate", "mate"],        1, 5),
    (["chá", "cha"],                          1, 1),
    (["erva-mate"],                           1, 20),
    # ── Outros naturais ───────────────────────────────────────────────
    (["água mineral", "agua mineral"],        1, 0),
    (["mel de abelha"],                       1, 309),
]

# ─────────────────────────────────────────────────────────────────────
# VALORES CALÓRICOS PADRÃO (kcal/100g) por categoria
# Usados como fallback dentro de cada grupo NOVA
# ─────────────────────────────────────────────────────────────────────

KCAL_DEFAULT = {
    1: 150,   # in natura (média conservadora)
    2: 400,   # ingredientes culinários
    3: 220,   # processados
    4: 350,   # ultraprocessados
}

NOVA_ROTULOS = {
    1: "NOVA 1 — In natura / minimamente processados",
    2: "NOVA 2 — Ingredientes culinários",
    3: "NOVA 3 — Processados",
    4: "NOVA 4 — Ultraprocessados",
}


# ─────────────────────────────────────────────────────────────────────
# FUNÇÃO DE CLASSIFICAÇÃO
# ─────────────────────────────────────────────────────────────────────

def normalizar(s):
    """Converte para minúsculas sem acentos para comparação."""
    s = unicodedata.normalize("NFD", str(s).lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")

def classificar_produto(nome):
    """
    Retorna (nova_grupo, kcal_por_100g) para um produto dado seu nome.
    Avalia NOVA 4 → NOVA 3 → NOVA 2 → NOVA 1 em ordem.
    """
    n = normalizar(nome)

    # Remove o prefixo numérico para focar no nome descritivo
    # Ex: "7.5.3 Mortadela" → "mortadela"
    nome_sem_prefix = re.sub(r"^\d+(\.\d+)*\s*", "", n).strip()

    def bate(keywords):
        """
        True se TODAS as keywords (AND) estiverem no nome normalizado.
        Com keywords normalizadas, sinônimos como ["pão de forma","pao de forma"]
        convergem para o mesmo token após normalize() → efetivamente OR.
        """
        if isinstance(keywords, str):
            kn = normalizar(keywords)
            return kn in nome_sem_prefix or kn in n
        return all(normalizar(k) in nome_sem_prefix or normalizar(k) in n
                   for k in keywords if isinstance(k, str))

    # Avalia NOVA 4 primeiro (mais restritivo)
    for keywords, nova, kcal in REGRAS_NOVA4:
        if bate(keywords):
            return nova, kcal

    # NOVA 3
    for keywords, nova, kcal in REGRAS_NOVA3:
        if bate(keywords):
            return nova, kcal

    # NOVA 2
    for keywords, nova, kcal in REGRAS_NOVA2:
        if bate(keywords):
            return nova, kcal

    # NOVA 1 (regras explícitas)
    for keywords, nova, kcal in REGRAS_NOVA1:
        if bate(keywords):
            return nova, kcal

    # Fallback por adjetivo genérico
    if any(k in n for k in ["fresco", "fresca", "in natura"]):
        return 1, 120
    if any(k in n for k in ["conserva", "em lata", "enlatado"]):
        return 3, 100
    if any(k in n for k in ["industrializado", "industrializada", "pronto"]):
        return 4, 200
    if any(k in n for k in ["salgado", "salgada", "defumado", "defumada"]):
        return 3, 180

    # Fallback por número de grupo (para "Outros/Outras/não especificado")
    # Extrai o número do grupo pai do prefixo da categoria
    # Ex: "7.5.11 Outras" → grupo pai 7 → carnes → NOVA 1
    m = re.match(r"^(\d+)\.", nome)
    grupo_pai = int(m.group(1)) if m else None

    NOVA_POR_GRUPO_PAI = {
        1:  (1, 340),   # cereais e leguminosas
        2:  (1,  25),   # hortaliças
        3:  (1,  60),   # frutas
        4:  (1, 580),   # cocos, castanhas
        5:  (1, 358),   # farinhas, féculas, massas
        6:  (3, 290),   # panificados (pão simples = NOVA 3)
        7:  (1, 200),   # carnes bovinas e suínas (frescas)
        8:  (1, 120),   # vísceras
        9:  (1, 110),   # pescados
        10: (1, 175),   # aves e ovos
        11: (3, 180),   # laticínios (leite/queijo = processado)
        12: (2, 387),   # açúcares e doces
        13: (2,  50),   # sais e condimentos
        14: (2, 884),   # óleos e gorduras
        15: (1,  30),   # bebidas (chá, café = NOVA 1 por padrão)
        16: (4, 280),   # alimentos preparados
        17: (4, 200),   # outros produtos industrializados
    }

    if grupo_pai in NOVA_POR_GRUPO_PAI:
        return NOVA_POR_GRUPO_PAI[grupo_pai]

    return None, None


def is_produto_folha(categoria):
    """True se for produto individual (ex: 7.5.3), False se grupo (ex: 7. ou 7.5)."""
    s = str(categoria).strip()
    return bool(re.match(r"^\d+\.\d+\.\d+", s))


# ─────────────────────────────────────────────────────────────────────
# CARREGAMENTO E CLASSIFICAÇÃO
# ─────────────────────────────────────────────────────────────────────
