# painel-san

Indicadores de segurança alimentar e nutricional no Brasil — e uma medida de quanto
os dados públicos permitem, de fato, acompanhá-los.

O pacote faz duas coisas que costumam andar separadas:

- **mede o indicador**, a partir das pesquisas domiciliares do IBGE;
- **mede a condição do dado** que sustenta o indicador: se está atual segundo o
  calendário que o próprio órgão publicou, se é legível por máquina, se alcançou a
  cobertura amostral que o órgão declarou, e em que eixos ele desagrega.

A segunda é a menos comum, e é o que distingue este repositório de um painel de
dados: ele foi construído para que a **ausência** de dado seja mensurável, datada e
verificável contra o documento primário que a promete.

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

### E o problema de que ninguém fala

Há uma pergunta anterior a essas, que os painéis costumam pular: **o dado permite
responder?** No caso da segurança do alimento, quase sempre a resposta é "em parte",
e o "em parte" não está escrito em lugar nenhum.

O Programa de Análise de Resíduos de Agrotóxicos em Alimentos mede cada alimento uma
vez a cada três anos, publica só em PDF, e em seis dos catorze alimentos do ciclo
2024 ficou abaixo da meta amostral que a própria Anvisa calculou. Nada disso é
segredo — está nos documentos oficiais. Mas está espalhado por relatórios, portarias
e planos plurianuais, em formatos que exigem um humano para serem lidos.

Este pacote transforma essas promessas em código verificável: cada fonte carrega a
régua **e o documento de onde a régua veio**, e cada afirmação sobre atraso ou
insuficiência é medida contra o que o próprio órgão declarou. Nunca contra um padrão
nosso.

## Estado

**v0.1.0 — em construção.** Estão prontos e testados, todos independentes de
interface:

| Módulo | O que faz |
|---|---|
| `modulos/san/nova` | classificação NOVA das 391 categorias da POF |
| `modulos/san/ingestao` | da tabela do SIDRA a Parquet versionado |
| `modulos/alimento_seguro/fontes` | catálogo de cinco fontes de vigilância, com régua e procedência |
| `modulos/alimento_seguro/latencia` | avaliação em quatro dimensões independentes |
| `modulos/alimento_seguro/registrador` | observa as fontes mensalmente e acumula histórico |
| `modulos/alimento_seguro/para` | extrai o relatório do PARA do PDF, validando contra os totais publicados |
| `modulos/alimento_seguro/pagina` | o mapa de frieza |

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

## Medindo a condição do dado

Cada fonte do catálogo carrega a régua que o órgão declarou **e onde ele a declarou**:

```python
from painel_san.modulos.alimento_seguro import fontes

fontes.MS_SISAGUA_AGROTOXICOS.periodicidade_meses
# 6
fontes.MS_SISAGUA_AGROTOXICOS.regua_fonte
# "Anexo 13 do Anexo XX da Portaria de Consolidação nº 5/2017, linha
#  'Demais parâmetros', nota (8)... Redação vigente dada pela Portaria
#  GM/MS nº 2.472, de 28/09/2021..."
fontes.MS_SISAGUA_AGROTOXICOS.regua_verificada
# True   -> conferido no documento primário, não em fonte secundária
```

Esse campo não é cerimônia. Das cinco réguas do catálogo, **as duas que vinham de
fonte secundária — uma reportagem e a página institucional do próprio órgão —
estavam erradas, e as duas erravam para o mesmo lado: cobrar mais do que a norma
exige.** O SISAGUA constava como trimestral e é semestral; o IBAMA constava como
semestral e virou anual pelo Decreto 10.833/2021. Régua com
`regua_verificada=False` não deve sustentar afirmação pública.

A avaliação devolve quatro dimensões separadas, porque têm remédios diferentes:

```python
from datetime import date
from painel_san.modulos.alimento_seguro import latencia, para

avaliacoes = para.avaliar_plano(para.ler_csv("dados/para_2024.csv"),
                                hoje=date.today())
soja = [a for a in avaliacoes if a.unidade == "soja"][0]

soja.temporal     # 'no prazo'
soja.amostral     # 'abaixo da meta declarada'
soja.cobertura_da_meta   # 0.368  -> 85 de 231 amostras
soja.confianca    # 'moderada'
```

Repare que a soja está **no prazo e abaixo da meta ao mesmo tempo**. Colapsar isso
numa cor só faria o painel mentir: publicar em CSV não resolve amostra pequena, e
coletar mais amostras não resolve o PDF.

### Extrair o relatório do PARA

O relatório sai só em PDF. O extrator se recusa a gravar se a soma não fechar com os
dois totais que a Anvisa publica no corpo do texto:

```bash
python -m painel_san.modulos.alimento_seguro.para relatorio_para_2024.pdf
# VALIDAÇÃO: 3084 amostras, 20.6% insatisfatórias — bate com os dois totais publicados
```

O PDF não entra no repositório; o que se versiona é a tabela extraída em
`dados/para_2024.csv`, pequena o bastante para ser conferida à mão contra o
documento.

### A interface

```bash
pip install -e ".[app]"
streamlit run app.py
```

O **mapa de frieza** acende onde não há dado. A grade é o Plano Plurianual —
36 alimentos — e as células se dividem em cinco leituras que nunca são somadas:
**sem resultado público** (a janela de medição fechou e nada saiu), **medido aquém
da régua**, **pendência nossa** (ainda não apuramos aquele ciclo), ausência
planejada e medido dentro da régua.

Em setembro de 2026, com os ciclos 2023 e 2024 apurados, o plano está assim:
dez alimentos sem nenhum resultado público — todo o ciclo 2025, encerrado em
dezembro e ainda não publicado — e nove medidos abaixo da meta amostral que a
própria Anvisa calculou.

Sobre os dez, o instrumento **não diz que a Anvisa está atrasada**, e a razão é o
achado: o Plano Plurianual promete *medir* cada alimento uma vez por ciclo e não
declara prazo algum para *publicar* o resultado. Não há régua contra a qual cobrar.
O que se afirma é o verificável — a janela fechou há nove meses e o resultado não
apareceu.

O balde "pendência nossa" existe
porque um instrumento que mede a falta alheia precisa medir a própria com o mesmo
rigor.

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

**Indicadores.** PNAD 2004/2009/2013 · POF 2002-2003/2008-2009/2017-2018 ·
PNAD Contínua 2023/2024 (IBGE) · VIGISAN 2021 (Rede PENSSAN).

**Vigilância do alimento.** Cinco fontes catalogadas, com a régua de cada uma:

| Fonte | Órgão | Periodicidade | Régua conferida no primário |
|---|---|---|---|
| Relatórios de comercialização de agrotóxicos | IBAMA | 12 meses | sim — art. 41 do Dec. 4.074/2002, red. Dec. 10.833/2021 |
| Monografias — limites máximos de resíduo | ANVISA | sem calendário | sim — o CSV traz `DT_ATUALIZACAO` |
| PARA | ANVISA | 36 meses | sim — Plano Plurianual 2023-2025 |
| SISAGUA, parâmetro agrotóxicos | Ministério da Saúde | 6 meses | sim — Anexo 13 do Anexo XX |
| PNCRC | MAPA | 12 meses | **não** — falta ler a Portaria SDA/MAPA 1.266/2025 |

A última coluna é parte do dado, não metadado: uma classificação apoiada em régua
não conferida sai com confiança mais baixa, e a interface diz isso.

## Como contribuir

Ainda não há `CONTRIBUTING.md` formal — abra uma issue descrevendo o que encontrou.

Relatos de classificação NOVA divergente são especialmente bem-vindos, e há uma
forma que ajuda muito: mande o nome exato da categoria da POF, o grupo que o pacote
atribui, o grupo que você esperava e a justificativa. Com isso o caso vira uma linha
em `CASOS_CONHECIDOS`, e a suíte passa a proteger contra ele para sempre.

Igualmente bem-vindo, e mais raro: **uma régua do catálogo que esteja errada.** Se
você leu o ato normativo e a periodicidade, a meta amostral ou a procedência não
batem, mande o artigo e o dispositivo. Duas das cinco já caíram assim, e as duas
faziam o instrumento cobrar mais do que a norma exige — o erro que mais interessa
encontrar, porque é o que o derrubaria em público.

## Licença

MIT. Ver [LICENSE](LICENSE).

## Referências da classificação

- Monteiro CA, Cannon G, Levy RB, et al. NOVA. The star shines bright.
  *World Nutrition*, 2016;7(1-3):28-38.
- Ministério da Saúde. *Guia Alimentar para a População Brasileira*. 2ª ed. 2014.
- NEPA-UNICAMP. *Tabela Brasileira de Composição de Alimentos (TACO)*. 4ª ed. 2011.
