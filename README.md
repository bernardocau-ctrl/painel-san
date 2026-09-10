# painel-san

Painel de insegurança alimentar e nutricional no Brasil, construído sobre as
pesquisas domiciliares do IBGE.

Produto técnico da dissertação de mestrado em Segurança Alimentar e Nutricional
(PPGSAN/UNIRIO) de Bernardo Castanho Santos Caú.

**Painel publicado:** <https://bernardocau-ctrl.github.io/dashboardsan/>

---

## O problema que resolve

Os indicadores brasileiros de segurança alimentar estão espalhados por pesquisas
com desenhos, períodos e unidades de análise diferentes: a EBIA aparece em
suplementos da PNAD (2004, 2009, 2013) e da PNAD Contínua (2023, 2024); a aquisição
alimentar domiciliar vem da POF (2002-2003, 2008-2009, 2017-2018); o orçamento
familiar, de outra tabela da mesma POF. Cruzá-las exige reprocessar microdados com
peso amostral, harmonizar categorias que mudaram de nome entre edições, e manter a
convenção de arredondamento que o IBGE usa nas tabelas publicadas.

Quem quer responder uma pergunta simples — a insegurança alimentar caiu no meu
estado? o consumo de ultraprocessados acompanha a renda? — costuma refazer esse
trabalho do zero. Este pacote faz o reprocessamento uma vez, expõe o resultado como
dado tabular leve, e o apresenta num painel.

## Estado

**v0.1.0 — em construção.** O repositório traz hoje a classificação NOVA e a
ingestão da aquisição alimentar domiciliar, ambas testadas e independentes de
interface. A camada de visualização e o módulo de vigilância de alimentos
contaminados por defensivos agrícolas (PARA/ANVISA) entram nas próximas versões.

O painel publicado hoje é um HTML gerado por um fluxo anterior, que este pacote está
substituindo.

## Instalação

```bash
git clone https://github.com/bernardocau-ctrl/painel-san
cd painel-san
pip install -e ".[dev]"
```

Requer Python 3.10 ou superior. As dependências são resolvidas pelo `pyproject.toml`.

## Uso

```python
from painel_san.modulos.san import nova

nova.classificar_produto("16.1.8 Salgadinho")
# (4, 530)   -> NOVA 4, 530 kcal/100 g

nova.classificar_produto("1.1.2 Arroz polido")
# (1, 358)   -> NOVA 1, 358 kcal/100 g
```

A classificação segue Monteiro et al. (2016) e usa densidades calóricas da TACO
(NEPA-UNICAMP, 2011). O módulo é puro: não lê arquivo, não escreve arquivo e não
importa Streamlit — é isso que o torna testável sem subir nenhuma interface.

Os indicadores já processados estão em `dados/processado`, em Parquet:

```python
import pandas as pd

br = pd.read_parquet("dados/processado/nova_brasil.parquet")
br[br.nova_grupo == 4][["periodo", "pct_calorias"]]
#   periodo  pct_calorias
#      2002          10.7
#      2008          13.1
#      2018          15.2
```

Quatro arquivos, 30 KB no total: `nova_brasil`, `nova_regiao`, `nova_uf` e
`nova_mapa` — este último é o mapeamento auditável produto a produto.

Para reprocessar a partir da tabela bruta do SIDRA:

```bash
python -m painel_san.modulos.san.ingestao caminho/para/tabela_2393.csv
```

## Testes

```bash
pytest
```

Rodam em menos de um segundo e não precisam dos microdados: a fixture
`tests/fixtures/categorias_pof_2393.txt` traz os nomes das 391 categorias da tabela
2393 do SIDRA.

Os casos não são hipotéticos. Cada um em `CASOS_CONHECIDOS` é um defeito que existiu
no pipeline e passou meses sem ser notado, porque nenhum deles produzia erro:

- Uma regra genérica para `sal` casava por substring dentro de *salgado* e mandava
  salgadinho, biscoito salgado e carne salgada para NOVA 2 com densidade calórica
  zero. Com kcal zero o item não é mal classificado — ele **desaparece do cálculo**,
  entrando com zero no numerador e no denominador.
- Listas de sinônimos eram avaliadas como conjunção. `["biscoito", "bolacha"]` exigia
  as duas palavras no mesmo nome e nunca disparava, então todo biscoito caía no
  padrão do grupo "panificados" como NOVA 3. Corrigir isso moveu a participação
  calórica de ultraprocessados de 11,3% para 15,2% em 2017-2018.

`test_nenhuma_regra_morta_com_dano` generaliza o segundo caso: uma regra nova que
nunca dispara e cujos produtos caem em grupo diferente reprova a suíte até ser
avaliada.

## Dados

Os microdados brutos do IBGE — 1,9 GB de PNAD, PNAD Contínua e POF — **não** entram
no repositório. Ficam em `dados/bruto/`, ignorado pelo git. O pipeline os lê de lá e
grava o derivado em `dados/processado/`, que é leve e versionado, para que qualquer
pessoa reproduza as análises sem baixar nada do IBGE.

A proporção é 1,9 GB de entrada para 30 KB de saída. É essa razão que torna a
separação óbvia: reprocessar microdados a cada execução seria inviável no CI e
desnecessário, porque o resultado é determinístico.

O dado versionado tem testes de contrato próprios — 27 UFs, três períodos, os quatro
grupos somando 100% em cada recorte, nenhum percentual fora de 0 a 100. Foi um
invariante desse tipo que falhou silenciosamente quando 40 células do painel
divergiram do SIDRA por convenção de arredondamento.

## Fontes

PNAD 2004/2009/2013 · POF 2002-2003/2008-2009/2017-2018 · PNAD Contínua 2023/2024
(IBGE) · VIGISAN 2021 (Rede PENSSAN).

## Como contribuir

Ainda não há `CONTRIBUTING.md` formal — entra na v0.2.0, junto com a camada de
visualização. Por enquanto, abra uma issue descrevendo o que encontrou.

Relatos de classificação NOVA divergente são especialmente bem-vindos, e há uma
forma que ajuda muito: mande o nome exato da categoria da POF, o grupo que o pacote
atribui, o grupo que você esperava e a justificativa. Com isso o caso vira uma linha
em `CASOS_CONHECIDOS`, e a suíte passa a proteger contra ele para sempre.

## Licença

MIT. Ver [LICENSE](LICENSE).

## Referências da classificação

- Monteiro CA, Cannon G, Levy RB, et al. NOVA. The star shines bright.
  *World Nutrition*, 2016;7(1-3):28-38.
- Ministério da Saúde. *Guia Alimentar para a População Brasileira*. 2ª ed. 2014.
- NEPA-UNICAMP. *Tabela Brasileira de Composição de Alimentos (TACO)*. 4ª ed. 2011.
