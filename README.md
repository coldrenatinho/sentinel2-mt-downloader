# Sentinel-2 MT Downloader

Aplicação desktop para catalogar, filtrar, baixar, visualizar e sincronizar
imagens Sentinel-2 de Mato Grosso. A GUI PySide6 é a interface principal
distribuída pelo projeto. A TUI e a CLI continuam disponíveis sobre o mesmo
núcleo de serviços para uso avançado e automação.

> O objetivo atual é preparar um conjunto de imagens confiável e reproduzível
> para análise geoespacial e futuros experimentos de classificação de áreas de
> soja em Mato Grosso.

## Principais recursos

- consulta ao STAC do INPE/Brazil Data Cube;
- filtro de cenas por nuvens e sombra usando a banda SCL;
- download configurável de `B02`, `B03`, `B04`, `B05`, `B06`, `B07`,
  `B08`, `B8A`, `B11`, `B12`, `NDVI` e `EVI`;
- camadas auxiliares `SCL`, `CLEAROB`, `TOTALOB` e `PROVENANCE`, quando disponíveis;
- geração de patches GeoTIFF multibanda georreferenciados sem redimensionamento;
- RGB PNG de dataset com stretch fixo e preview JPEG com percentis;
- filtro de nuvem e dados válidos por patch;
- catálogo específico `catalogo/patches.csv` e manifesto JSON opcional por patch aprovado;
- catálogo CSV reproduzível das cenas avaliadas;
- GUI desktop em PySide6 com mapa, perfis locais e logs em tempo real;
- TUI em Textual para uso completo pelo terminal;
- CLI para automação, scripts e servidores;
- análise agrícola local por detecção em patches RGB, com estatísticas, overlays,
  relatório PDF e histórico SQLite;
- sincronização direta com Google Drive, sem `rclone`;
- divisão dos arquivos em lotes configuráveis;
- preservação da hierarquia local e atualização de arquivos já existentes;
- builds Linux `.deb`, `.rpm`, `.pkg.tar.zst`, `PKGBUILD` e binário x86_64;
- testes unitários e funcionais sem depender de chamadas reais ao Google Drive.

## Fonte dos dados

| Item | Valor padrão |
| --- | --- |
| Provedor | INPE / Brazil Data Cube |
| STAC | `https://data.inpe.br/bdc/stac/v1/` |
| Coleção | `S2-16D-2` |
| Dados de origem | Sentinel-2 MSI Level-2A |
| Produto padrão | cubo BDC composto a cada 16 dias (`S2-16D-2`) |
| Grade do produto padrão | geralmente 10 m; não confundir com resolução nativa de cada banda |
| Composição temporal | 16 dias |

O endpoint STAC e a coleção podem ser alterados em `config/config.yaml` ou pela
GUI; os demais itens descrevem o produto usado como padrão pelo projeto.

## Início rápido

### Requisitos

- Python 3.10 ou mais recente;
- acesso à internet para consultar o INPE e instalar as dependências;
- `python3-venv` em distribuições Debian/Ubuntu que não incluem `venv` por
  padrão.

Os inicializadores criam uma `.venv` dentro do projeto. Isso evita o erro de
ambiente gerenciado da PEP 668 e não modifica os pacotes Python do sistema.

### Interface gráfica — recomendada

```bash
python iniciar_gui.py
```

Na primeira execução, o inicializador cria o ambiente virtual e instala as
dependências da GUI. Nas próximas execuções, ele reutiliza o ambiente e somente
reinstala dependências quando os arquivos de requisitos mudarem.

Pela GUI é possível:

- selecionar a área no mapa com `Shift + arrastar`; ele é carregado ao abrir a
  página e as coordenadas continuam editáveis manualmente sem conexão;
- definir período, bandas, limites de nuvens e opções de preview;
- catalogar ou baixar cenas;
- apontar diretamente para o JSON OAuth do Google;
- configurar lotes e sincronizar com o Drive;
- acompanhar a saída, cancelar operações e visualizar previews;
- executar **Analisar região com IA**, consultar estatísticas e overlays e abrir
  relatórios do histórico local;
- salvar perfis locais por região sem armazenar credenciais.

Para apenas preparar o ambiente gráfico:

```bash
python iniciar_gui.py --setup-only
```

Consulte [README_GUI.md](README_GUI.md) para detalhes e solução de problemas da
interface.

Depois de instalar um pacote `.deb`, `.rpm` ou `.pkg.tar.zst`, abra o aplicativo
pelo menu do sistema ou execute:

```bash
sentinel2-mt
```

O executável sem argumentos e o atalho do sistema abrem sempre a GUI.

### Interface de terminal

```bash
python iniciar_tui.py
```

A TUI permite catalogar, baixar, gerar o dataset local, executar a análise,
sincronizar, acompanhar logs e cancelar a operação atual. Use `Ctrl+Q` para sair
e `Ctrl+L` para limpar o log. Em uma instalação empacotada, use
`sentinel2-mt --tui`.

### Linha de comando

Prepare o ambiente sem abrir a TUI:

```bash
python iniciar_tui.py --setup-only
```

Em uma instalação empacotada, prefixe as opções com `sentinel2-mt --cli`.
As opções antigas sem esse prefixo continuam aceitas para compatibilidade.

No Linux/macOS, execute a CLI com `.venv/bin/python`. No Windows, substitua por
`.venv\Scripts\python.exe`.

Catalogar sem baixar GeoTIFFs:

```bash
.venv/bin/python src/baixar_inpe_mt.py
```

Baixar uma cena para validação:

```bash
.venv/bin/python src/baixar_inpe_mt.py --baixar --max-itens 1
```

Baixar uma cena e gerar patches de 512 pixels:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --baixar --gerar-dataset --patch-size 512 --max-itens 1
```

Regenerar o dataset de 512 pixels usando os GeoTIFFs já existentes, sem STAC e
sem novo download:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --gerar-dataset --patch-size 512 --max-itens 0
```

O modo local considera somente as cenas no período do YAML ou de
`--inicio/--fim` e respeita `--max-itens`; use `--max-itens 0` para remover o
limite de cenas.

Gerar patches de 256 pixels com stride 256:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --gerar-dataset --patch-size 256 --patch-stride 256 --max-itens 0
```

Baixar até cinco cenas em um período específico:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --baixar \
  --inicio 2025-09-01 \
  --fim 2026-04-30 \
  --max-itens 5
```

Baixar/processar as cenas, gerar patches e executar a análise agrícola local:

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --analisar --inicio 2025-09-01 --fim 2026-04-30 \
  --patch-size 512 --patch-stride 512 --max-itens 5
```

`--analisar` usa os mesmos parâmetros de período, limite de cenas e patches da
coleta. Ele não pode ser combinado com `--sincronizar`. Antes de executar,
forneça um peso Ultralytics YOLO compatível exatamente em
`src/sentinel2_mt/analise/models/agricultura.pt` na árvore de desenvolvimento.
Esse arquivo `.pt` não está incluído no repositório; por isso, a inferência real
não foi validada neste estado do código.

Exibir todas as opções:

```bash
.venv/bin/python src/baixar_inpe_mt.py --help
```

## Configuração

O arquivo padrão é `config/config.yaml`. Ele concentra:

- endpoint STAC e coleção;
- nome, UF e bounding box da área;
- período de busca e bandas;
- filtros de qualidade e nuvens;
- tamanho e qualidade do preview;
- stretch independente para preview e RGB do dataset;
- tamanho, stride, nuvem, dados válidos mínimos e limite de patches por cena;
- diretórios e catálogos separados para cenas e dataset;
- diretórios, timeout e tamanho de chunk;
- modelo, limiares, tamanho de inferência, saídas e histórico da análise;
- credenciais, destino, extensões e lotes da sincronização.

A seção de análise e seus defaults no ambiente de desenvolvimento são:

```yaml
analise:
  modelo: analise/models/agricultura.pt
  modelo_sha256: ''
  confianca_minima: 0.25
  iou_maximo: 0.45
  tamanho_inferencia_px: 640
  pasta: data/analises
  historico: data/historico-analises.sqlite3
  gerar_relatorio: true
  max_imagens: 1000
```

`max_imagens: 1000` limita o uso de memória e disco; zero remove o limite e deve
ser usado com cautela em catálogos grandes. O SHA-256 aprovado deve ser gravado
no `model_metadata.json`; a cópia opcional no YAML precisa coincidir. Veja
[docs/modelo-ia.md](docs/modelo-ia.md) para instalação, metadata, CPU/GPU,
substituição do modelo e limitações.

As variáveis abaixo podem sobrescrever valores sensíveis sem alterar o YAML:

```bash
export GOOGLE_OAUTH_JSON=/caminho/client_secret.json
export GOOGLE_TOKEN_JSON=/caminho/google-token.json
export GOOGLE_PASTA_ID=root
```

Também é possível usar outro arquivo de configuração:

```bash
.venv/bin/python src/baixar_inpe_mt.py --config /caminho/config.yaml
```

Consulte [docs/dataset.md](docs/dataset.md) para a referência completa de
bandas, resolução nativa, qualidade, alinhamento e catálogo de patches.

## Arquivos gerados

Com os defaults e todos os assets disponíveis, uma cena aprovada é organizada
por data e identificador como no exemplo abaixo. Assets ausentes são omitidos;
os produtos do dataset dependem de suas flags e `rgb.png` exige B04/B03/B02.

```text
data/sentinel2/
└── 2026-02-02/
    └── ID_DA_CENA/
        ├── B02.tif
        ├── B03.tif
        ├── B04.tif
        ├── B05.tif
        ├── B06.tif
        ├── B07.tif
        ├── B08.tif
        ├── B8A.tif
        ├── B11.tif
        ├── B12.tif
        ├── NDVI.tif
        ├── EVI.tif
        ├── qualidade/
        │   ├── SCL.tif
        │   ├── CLEAROB.tif
        │   ├── TOTALOB.tif
        │   └── PROVENANCE.tif
        └── preview_rgb.jpg

data/dataset/
└── 2026-02-02/
    └── ID_DA_CENA/
        └── ID_DA_CENA_HASH_x000000_y000000_512/
            ├── multiband.tif
            ├── rgb.png
            └── metadata.json

catalogo/
├── catalogo_imagens.csv
└── patches.csv

data/analises/analise-HASH/
├── PATCH_ID-deteccoes.png
├── resultado.json
└── relatorio.pdf              # se analise.gerar_relatorio=true

data/historico-analises.sqlite3
```

Os GeoTIFFs em `data/sentinel2` são a fonte científica e nunca são
redimensionados ou convertidos para 8 bits. `multiband.tif` é o recorte
georreferenciado para ML, `rgb.png` é uma representação RGB 8-bit do mesmo
patch e `preview_rgb.jpg` é apenas visualização reduzida. JPEG não é fonte do
dataset de treinamento.

O projeto gera RGB PNG por patch em vez de um `rgb_dataset.png` de cena inteira,
evitando uma imagem enorme e redundante. Os PNGs mantêm a dimensão do patch;
os valores científicos permanecem nos GeoTIFFs.

O produto padrão baixa rasters científicos GeoTIFF. Se outra coleção fornecer
JP2, a extensão original é preservada e o modo local também a reconhece. Em
pacotes Linux, os defaults ficam sob `~/.local/share/sentinel2-mt`; os caminhos
`data/` e `catalogo/` acima correspondem à execução pelo código-fonte.

> Aumentar artificialmente a dimensão da imagem não aumenta a resolução
> espacial real do Sentinel-2.

O catálogo padrão é gravado em `catalogo/catalogo_imagens.csv`.

## Sincronização com Google Drive

A integração usa diretamente a API oficial do Google Drive. Não é necessário
instalar ou configurar `rclone`.

### Credencial OAuth

Use um JSON de cliente OAuth do tipo **Desktop app / aplicativo para
computador**. O arquivo pode ficar em qualquer diretório: basta selecioná-lo na
GUI ou informá-lo com `--oauth-json`. O JSON real e o token local não devem ser
versionados.

```bash
.venv/bin/python src/baixar_inpe_mt.py \
  --sincronizar \
  --oauth-json /caminho/client_secret.json \
  --lote 25
```

Na primeira execução:

1. o navegador abre o seletor de contas do Google;
2. o retorno ocorre em `127.0.0.1` por uma porta temporária;
3. uma página local informa se a autenticação foi concluída ou recusada;
4. o token é salvo no caminho configurado e reutilizado nas próximas execuções.

O projeto solicita apenas o escopo `drive.file`, limitado aos arquivos criados
ou abertos pela própria aplicação.

Se o projeto OAuth estiver em **Testing**, o e-mail usado no login precisa estar
em **Google Auth Platform → Audience → Test users**. Caso contrário, o Google
retornará `Error 403: access_denied`. Essa restrição é do projeto OAuth e não
pode ser contornada pelo código local.

### Lotes e hierarquia

O tamanho padrão vem de `sincronizacao.tamanho_lote`. `--lote` altera o valor
somente para a execução atual. Por padrão, são sincronizados `.tif`, `.tiff`,
`.jpg` e `.jpeg`.

A sincronização atual percorre apenas `download.pasta`: cobre cenas científicas
e previews configurados, mas não envia automaticamente `dataset.pasta`, PNG,
JSON ou `patches.csv`.

A sincronização:

- divide os arquivos sem perder a ordem;
- preserva as pastas de data e cena;
- cria pastas remotas quando necessário;
- atualiza arquivos de mesmo nome já existentes;
- reutiliza o token OAuth nas execuções seguintes.

## Arquitetura

O projeto é um monólito modular: GUI, TUI e CLI são distribuídas juntas, mas as
regras de negócio, processamento raster, análise e integrações ficam separadas
em módulos substituíveis. A arquitetura e o fluxo completo estão em
[docs/arquitetura-aplicacao.md](docs/arquitetura-aplicacao.md).

No fluxo gráfico de análise, a GUI inicia a CLI por `QProcess`; a CLI chama
`ServicoSentinel2`, gera patches RGB e multibanda, executa `DetectorAgricola`,
agrega estatísticas, grava overlays e JSON, gera o PDF opcional e registra o
histórico local. A TUI também delega a operação `--analisar` à mesma CLI.

Componentes principais:

| Componente | Responsabilidade |
| --- | --- |
| `ConfiguracaoProjeto` | Carregamento, expansão e validação da configuração |
| `ServicoSentinel2` | Caso de uso de catalogação, filtro e download |
| `SincronizadorGoogleDrive` | OAuth, hierarquia remota, lotes e uploads |
| `ClienteDownloadHTTP` | Transferência HTTP com timeout e progresso |
| `ProcessadorImagem` | Leitura de bandas, filtros e geração do preview |
| `GeradorDataset` | Janelas, alinhamento, qualidade e produtos dos patches |
| `ServicoAnaliseAgricola` | Orquestra patches, detector, estatísticas, overlays, PDF e histórico |
| `DetectorAgricola` | Adaptador local para inferência Ultralytics YOLO em CPU ou CUDA |
| `ResolvedorAssets` | Normalização de nomes de assets entre coleções STAC |
| `RepositorioCatalogoCSV` | Persistência reproduzível do catálogo |
| `RepositorioCatalogoPatchesCSV` | Catálogo incremental e rastreável dos patches |
| `AplicacaoCLI` | Automação por linha de comando |
| `SentinelTUI` | Interface de terminal |
| `MainWindow` | Interface gráfica desktop |

As dependências externas podem ser substituídas nos construtores, permitindo
testes com serviços simulados e sem mutações no Google Drive.

### Estrutura resumida

```text
sentinel2-mt-downloader/
├── config/                  # configuração e exemplo OAuth
├── packaging/               # DEB, RPM, Arch e PyInstaller
├── src/
│   ├── baixar_inpe_mt.py    # entrada CLI compatível
│   ├── gerar_config_gui.py  # GUI PySide6
│   ├── tui.py               # TUI Textual
│   └── sentinel2_mt/        # serviços e adaptadores
├── tests/                   # testes unitários, Qt e smoke tests
├── iniciar_gui.py
├── iniciar_tui.py
├── requirements.txt
└── requirements-gui.txt
```

## Testes

Os testes usam serviços simulados para os fluxos do Google Drive e podem ser
executados sem enviar arquivos ou criar pastas remotas:

```bash
.venv/bin/python -m unittest discover -v
```

Em ambientes sem display, use o backend Qt offscreen:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -v
```

A suíte cobre também stretch, assets, janelas, georreferenciamento, alinhamento,
SCL por patch, dados válidos, RGB PNG, catálogo e pipeline sintético, além de
regras de serviço, Drive, OAuth, GUI, subprocessos e empacotamento.

## Pacotes Linux e releases

O workflow [`.github/workflows/packages.yml`](.github/workflows/packages.yml)
executa os testes, gera um binário autocontido com PyInstaller e produz:

- Debian/Ubuntu: `.deb`;
- Fedora/RHEL/openSUSE: `.rpm`;
- Arch Linux: `.pkg.tar.zst` e `PKGBUILD`;
- binário Linux x86_64 e `SHA256SUMS`.

Os pacotes incluem a GUI PySide6 e a iniciam quando o executável é chamado sem
argumentos. As interfaces alternativas permanecem disponíveis com
`sentinel2-mt --tui` e `sentinel2-mt --cli ...`.

Para publicar uma versão, atualize `__version__` em
`src/sentinel2_mt/__init__.py`, crie uma tag com a mesma versão e envie-a:

```bash
git tag -a v2.0.0 -m "release: v2.0.0"
git push origin v2.0.0
```

Uma execução manual do workflow gera artefatos para validação sem publicar uma
GitHub Release. Consulte [packaging/README.md](packaging/README.md) para o build
local e os comandos de instalação. O padrão adotado para versões, branches,
commits e releases está documentado em
[docs/versionamento-e-commits.md](docs/versionamento-e-commits.md).

## Contribuindo por fork

Depois de criar o fork no GitHub, `origin` deve apontar para o seu fork e
`upstream` para o repositório original:

```bash
git clone git@github.com:SEU_USUARIO/sentinel2-mt-downloader.git
cd sentinel2-mt-downloader
git remote add upstream git@github.com:ORGANIZACAO/sentinel2-mt-downloader.git
git fetch upstream
```

Crie uma branch a partir da `main` atualizada:

```bash
git switch main
git pull --ff-only upstream main
git switch -c feat/minha-alteracao
```

Antes de publicar:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -v
git status
git push -u origin feat/minha-alteracao
```

Abra o Pull Request da branch do seu fork para `main` do repositório original.
No PR, descreva o problema, a solução, como foi testada e qualquer impacto em
configuração, OAuth ou empacotamento.

Evite incluir no commit:

- `config/google-oauth.json` ou `client_secret_*.json`;
- `config/google-token.json`;
- `.env`, bancos SQLite locais e credenciais;
- GeoTIFFs, previews ou outros arquivos grandes do dataset.

## Dados e segurança

Os diretórios de imagens, tokens, credenciais, ambientes virtuais e artefatos
de build são ignorados pelo Git. O repositório deve guardar somente código,
configurações sem segredos, testes e metadados necessários para reproduzir a
coleta.

Não use o GitHub como armazenamento das imagens Sentinel-2. Mantenha os dados
localmente ou sincronize-os com um destino apropriado, como o Google Drive.
