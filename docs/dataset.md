# Dataset Sentinel-2 para ML

## Produtos e integridade científica

O pipeline mantém quatro tipos de produto com finalidades distintas:

| Produto | Formato | Uso |
| --- | --- | --- |
| cena científica | raster original em `data/sentinel2` | fonte primária, análise e reprocessamento |
| patch científico | GeoTIFF multibanda em `data/dataset` | treinamento e análise geoespacial |
| RGB do patch | PNG 8-bit | modelos RGB e inspeção sem artefatos de compressão JPEG |
| preview da cena | JPEG reduzido | GUI e conferência humana |

Os rasters de origem nunca são sobrescritos, reduzidos ou convertidos para
`uint8`. A conversão para 0–255 ocorre somente no PNG/JPEG. O pipeline não gera
um PNG RGB da cena inteira por padrão; o RGB específico do dataset é o
o PNG RGB identificado por UUID em cada patch.

No produto padrão, os rasters científicos são GeoTIFF; coleções que forneçam
JP2 mantêm essa extensão. O PNG ainda é uma representação `uint8` e nunca
substitui os valores científicos.

> Aumentar artificialmente a dimensão da imagem não aumenta a resolução
> espacial real do Sentinel-2.

Não há upscale para 1 m, 2 m ou 5 m. Um patch 512 × 512 é lido diretamente com
`rasterio.windows.Window` e permanece 512 × 512.

## Bandas e resolução

| Banda | Informação | Resolução nativa Sentinel-2 |
| --- | --- | --- |
| B02 | azul | 10 m |
| B03 | verde | 10 m |
| B04 | vermelho | 10 m |
| B08 | infravermelho próximo | 10 m |
| B05, B06, B07 | red edge | 20 m |
| B8A | infravermelho próximo estreito | 20 m |
| B11, B12 | infravermelho de ondas curtas | 20 m |
| NDVI, EVI | índices fornecidos pela coleção | depende do produto |

Uma coleção pode entregar bandas de 20 m em uma grade reamostrada de 10 m. Isso
facilita o empilhamento, mas não cria detalhe nativo adicional. O GeoTIFF de
patch registra `NATIVE_RESOLUTION_M` por canal conhecido e o manifesto separa
resolução nativa da dimensão da grade.

Em uma grade de 10 m:

- 256 px × 10 m = 2,56 km;
- 512 px × 10 m = 5,12 km.

Se a grade de referência for 20 m, as extensões lineares serão o dobro. O campo
`pixel_size` do catálogo é a fonte correta para interpretar cada patch.

NDVI e EVI são reutilizados quando existem como assets. Se um deles não estiver
disponível, o pipeline registra a ausência e continua; cálculo local de índices
fica preparado como evolução futura, sem fabricar um asset nesta versão.

## Assets auxiliares

`SCL`, `CLEAROB`, `TOTALOB` e `PROVENANCE` são baixados para `qualidade/` quando
existem. Eles servem a controle de qualidade, seleção temporal e rastreabilidade,
e não são incluídos automaticamente como canais científicos do modelo.

No SCL, as classes ruins padrão são:

| Classe | Significado |
| --- | --- |
| 3 | sombra de nuvem |
| 7 | não classificado/baixa confiança |
| 8 | nuvem com probabilidade média |
| 9 | nuvem com probabilidade alta |
| 10 | cirrus |
| 11 | neve ou gelo |

Pixels SCL 0 e 1 não entram no denominador de nuvem. `CLEAROB` e `TOTALOB`
descrevem observações claras e totais no composto, quando fornecidos pela
coleção; `PROVENANCE` permite rastrear as observações de origem. A semântica
exata desses assets deve ser confirmada no metadado da coleção escolhida.

## Configuração

```yaml
qualidade:
  filtrar_nuvens: true
  nuvem_max_pct: 40
  manter_scl: true
  camadas_auxiliares: [SCL, CLEAROB, TOTALOB, PROVENANCE]

preview:
  gerar_rgb: true
  tamanho_max_px: 1600
  metodo: percentile
  percentil_min: 2
  percentil_max: 98
  qualidade_jpeg: 92

dataset:
  gerar: false
  pasta: data/dataset
  catalogo: catalogo/patches.csv
  rgb:
    gerar_png: true
    metodo: fixed
    minimo: 0
    maximo: 2000
  patches:
    habilitado: true
    tamanho_px: 512
    stride_px: 512
    nuvem_max_pct: 10
    dados_validos_min_pct: 90
    max_patches_por_cena: 100000
  gerar_geotiff_multibanda: true
  gerar_metadata_json: true
```

Configurações antigas continuam válidas. Sem `preview.metodo`, o comportamento
é `percentile`; sem a seção `dataset`, `dataset.gerar` é `false`.

### Stretch RGB

`fixed` aplica uma transformação radiometricamente consistente entre datas. Na
faixa padrão, 0 vira 0, 2000 vira 255 e os valores externos são recortados. É o
método recomendado para RGB de dataset.

`percentile` calcula os limites em cada imagem ou patch, oferecendo melhor
contraste visual, mas mudando a escala entre datas. Continua sendo o padrão do
preview humano.

Ambos os blocos aceitam os dois métodos. Por exemplo, um preview fixo e um RGB
de dataset por percentis podem ser selecionados assim:

```yaml
preview:
  metodo: fixed
  minimo: 0
  maximo: 2000

dataset:
  rgb:
    metodo: percentile
    percentil_min: 2
    percentil_max: 98
```

Os defaults continuam `preview.metodo: percentile` e
`dataset.rgb.metodo: fixed`.

## Janelas, alinhamento e georreferenciamento

Os offsets percorrem a grade em ordem de linha e coluna. O identificador é
determinístico, por exemplo:

```text
S2_SCENE_4f61a3b2c900_x000000_y000512_512
```

Cada GeoTIFF usa o CRS da banda de referência e um transform calculado com
`rasterio.windows.transform`. Width, height, bounds, pixel size, nodata/máscara,
dtype, cena, coleção e descrições dos canais são gravados no arquivo ou no
manifesto. O patch abre de forma independente em rasterio, GDAL e QGIS.
O hash estável incorpora coleção, data e ID original da cena, evitando colisões
sem usar UUID aleatório.

A preferência de grade de referência é B02, B03, B04 ou B08. Antes do
empilhamento, CRS, transform, width e height são comparados. Assets desalinhados
são expostos por `WarpedVRT` na grade de referência:

- refletância e índices contínuos: bilinear;
- SCL e outras classes categóricas: nearest.

O alinhamento ocorre durante a leitura e não altera os GeoTIFFs de origem. Um
GeoTIFF multibanda usa um dtype comum capaz de representar os canais presentes;
se os nodata de origem forem iguais, esse valor é mantido. Quando diferem, a
máscara válida do GeoTIFF preserva os pixels inválidos sem declarar um nodata
único incorreto.

## Qualidade por patch

O limite `qualidade.nuvem_max_pct` é um filtro preliminar da cena. Esse valor
global é uma estimativa amostrada em uma SCL reduzida para até 1400 pixels com
nearest. Já
`dataset.patches.nuvem_max_pct` é calculado na janela espacial de cada patch,
depois de alinhar SCL com nearest. Assim, uma cena com 30% de nuvens pode manter
um patch agrícola com 2%.

`valid_pixel_pct` é a interseção dos pixels válidos de todos os canais
científicos presentes. Janelas de borda são preenchidas como inválidas, nunca
redimensionadas. O patch é rejeitado quando fica abaixo de
`dados_validos_min_pct`.

Antes de percorrer as janelas, `max_patches_por_cena` limita a quantidade de
candidatos calculada a partir da grade e do stride, evitando configurações que
consumiriam recursos de forma acidental.

Sem SCL, o download da cena e os patches científicos continuam. O status fica
`APROVADO_SEM_SCL` e `cloud_pct` vazio, deixando explícito que o filtro de nuvem
não foi aplicado. Uma banda opcional ausente aparece em `missing_bands`; as
bandas disponíveis ainda formam o GeoTIFF multibanda.

## Catálogo e diretórios

O exemplo abaixo considera os defaults e os assets disponíveis. Bandas e
auxiliares ausentes são omitidos; os três produtos do patch são condicionados a
suas flags, e o RGB requer B04/B03/B02.

```text
data/
├── sentinel2/YYYY-MM-DD/SCENE_ID/
│   ├── B02.tif ... EVI.tif       # GeoTIFF padrão; JP2 é preservado quando fornecido
│   ├── qualidade/SCL.tif ... PROVENANCE.tif  # condicionais
│   └── preview_rgb.jpg            # se preview.gerar_rgb=true e RGB disponível
└── dataset/YYYY-MM-DD/SCENE_ID/PATCH_ID/
    ├── multiband.tif              # se habilitado
    ├── <uuid>.png                 # se habilitado e RGB disponível
    └── metadata.json              # patch aprovado, se habilitado

catalogo/
├── catalogo_imagens.csv
└── patches.csv
```

`patches.csv` é atualizado por `patch_id`, preservando cenas de execuções
anteriores. Ele registra também candidatos rejeitados, com `REJEITADO_NUVEM`,
`REJEITADO_NODATA` ou `ERRO`. Os campos `label`, `label_source` e
`label_confidence` existem vazios para uma integração futura com MapBiomas e,
quando preenchidos, são preservados em uma regeneração.

O esquema do CSV é:

```text
patch_id, scene_id, collection, date, bbox, crs, width, height, pixel_size,
cloud_pct, valid_pixel_pct, source_scene, rgb_png, geotiff_path, bands,
missing_bands, scl_path, CLEAROB, TOTALOB, PROVENANCE, status, erro,
label, label_source, label_confidence
```

`CLEAROB`, `TOTALOB` e `PROVENANCE` guardam caminhos dos assets auxiliares, não
valores escalares. O catálogo é atualizado por escrita atômica e bloqueio local.

O `metadata.json` evita achatar em CSV listas de bandas, bounds, resolução
nativa, caminhos de origem e políticas de resampling.

Os caminhos `data/` e `catalogo/` são defaults da execução pelo código-fonte.
Pacotes Linux usam `~/.local/share/sentinel2-mt` por padrão.

## Uso

Baixar uma cena sem gerar dataset:

```bash
.venv/bin/python src/baixar_inpe_mt.py --baixar --max-itens 1
```

Baixar e gerar patches 512:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --baixar --gerar-dataset --patch-size 512 --max-itens 1
```

Regenerar patches 512 das cenas locais, sem consultar o STAC:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --gerar-dataset --patch-size 512 --max-itens 0
```

Nos modos locais, somente pastas de data dentro do período do YAML ou de
`--inicio/--fim` são consideradas. `--max-itens 0` remove o limite de cenas.

Regenerar patches 256:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --gerar-dataset --patch-size 256 --patch-stride 256 --max-itens 0
```

`S2-16D-2` permanece a coleção padrão. Para usar `S2_L2A-1`, altere
`stac.colecao`; o resolvedor aceita aliases comuns de bandas sem espalhar
condicionais por coleção. A disponibilidade de índices e auxiliares varia, e
essas ausências são registradas sem abortar os demais assets.

A sincronização Google Drive atual percorre apenas `download.pasta`; o dataset,
seus PNG/JSON e `patches.csv` não são enviados automaticamente.

## Relação com a análise agrícola

`--analisar` primeiro executa a coleta com geração de dataset e depois seleciona
no `patches.csv` somente registros aprovados, dentro do período, que tenham
`rgb_png` local. O detector recebe o PNG identificado por UUID, com B04/B03/B02 em 8 bits; o
`multiband.tif` continua sendo o patch científico e não é alterado. Para cada
entrada, a análise cria um PNG de overlay separado.

As estatísticas agregam caixas, classes, confianças, presença de detecção por
tile, nuvens disponíveis e hashes de modelo/entradas. Elas não calculam área.
A bbox da configuração delimita a consulta, mas caixas em pixels não podem ser
convertidas em hectares sem escala, resolução espacial e geometria
georreferenciada validadas para esse fim. Consulte [modelo-ia.md](modelo-ia.md)
para o contrato do detector e [arquitetura-aplicacao.md](arquitetura-aplicacao.md)
para o fluxo da aplicação.

## Limitações

Sentinel-2 não resolve linhas de plantio, plantas individuais nem feições
menores que sua resolução espacial efetiva. Reamostragem melhora compatibilidade
de grade, não conteúdo. Nuvem, sombra, mistura de pixels, fenologia, diferença
entre composição temporal e aquisição individual e qualidade futura dos labels
continuam sendo fatores do experimento agrícola.
