# Arquitetura da aplicação

## Visão geral

O Sentinel-2 MT Downloader é um monólito modular em Python. GUI, TUI e CLI são
distribuídas como uma aplicação, enquanto configuração, coleta, processamento
raster, análise, persistência e Google Drive permanecem separados por módulos e
contratos substituíveis nos testes.

O fluxo-base é `GUI/TUI/CLI -> ConfiguracaoProjeto -> ServicoSentinel2`. A
análise acrescenta um caso de uso que reutiliza esse núcleo:

```text
GUI (QProcess) ou TUI (subprocess)
                |
                v
          CLI --analisar
                |
                v
    ServicoAnaliseAgricola
                |
                +--> ServicoSentinel2
                |      └--> cenas + patches RGB e multibanda
                |
                +--> DetectorAgricola sobre rgb.png
                |      └--> caixas, classes, confianças e metadata
                |
                +--> estatísticas agregadas
                +--> overlays PNG + resultado.json
                +--> relatório PDF opcional
                └--> histórico SQLite
```

## Interfaces e processo

`src/gerar_config_gui.py` coleta os campos, grava o YAML e inicia a CLI com
`QProcess`. A saída padrão e de erro é combinada no log. Quando a CLI conclui a
análise, emite `[ANALISE_RESULTADO] caminho/resultado.json`; a GUI lê esse JSON,
preenche a tela de análise e recarrega o histórico. Cancelar pela GUI encerra o
processo filho.

`src/tui.py` oferece as mesmas operações essenciais em Textual e também inicia
a CLI como subprocesso. A opção **Analisar região com IA** monta
`--analisar`, período, limite de cenas, tamanho e stride dos patches. A CLI é a
fronteira pública comum e rejeita o uso simultâneo de `--analisar` e
`--sincronizar`.

Na execução pelo repositório, a entrada compatível é
`src/baixar_inpe_mt.py`. Nos pacotes, `sentinel2-mt` abre a GUI sem argumentos;
`sentinel2-mt --tui` abre a TUI e `sentinel2-mt --cli ...` seleciona a CLI.

## Núcleo e módulos

| Módulo/componente | Responsabilidade |
| --- | --- |
| `ConfiguracaoProjeto` | Carrega YAML, expande ambiente, aplica compatibilidade e valida defaults |
| `ServicoSentinel2` | Consulta STAC, filtra, baixa, gera preview e aciona o dataset |
| `GeradorDataset` | Produz patches GeoTIFF multibanda, RGB PNG, metadata e catálogo |
| `ServicoAnaliseAgricola` | Coordena coleta, entradas aprovadas, detector, saídas e histórico |
| `DetectorAgricola` | Isola Ultralytics/Torch e normaliza o resultado do modelo |
| `calcular_estatisticas` | Agrega caixas, classes, confianças, tiles, nuvens e hashes |
| `GeradorRelatorioAnalise` | Gera PDF local com Matplotlib |
| `RepositorioHistoricoAnalises` | Persiste resumo, metadata e caminhos relativos em SQLite |
| `SincronizadorGoogleDrive` | Implementa OAuth `drive.file`, lotes e hierarquia remota |

Clientes externos e repositórios são injetáveis. Os testes usam fakes, imagens
sintéticas e diretórios temporários; não dependem de STAC, navegador, modelo
real ou Google Drive.

## Contrato dos dados da análise

A coleta preserva quatro papéis diferentes:

- cena científica: raster original em `download.pasta`;
- patch científico: `multiband.tif`, georreferenciado e com valores originais;
- representação RGB: `rgb.png` B04/B03/B02 em 8 bits, entrada do detector;
- preview: `preview_rgb.jpg`, destinado somente à inspeção da cena.

O overlay `PATCH_ID-deteccoes.png` é outra representação visual. Ele é criado a
partir do RGB e não sobrescreve o PNG de entrada nem o GeoTIFF multibanda.
Reamostragem usada para alinhar grades não aumenta a resolução espacial.

Com os defaults de desenvolvimento, cada análise usa um identificador
determinístico derivado da bbox, período, parâmetros, hash do modelo e hashes
das entradas:

```text
data/analises/analise-HASH/
├── PATCH_ID-deteccoes.png
├── resultado.json
└── relatorio.pdf              # opcional

data/historico-analises.sqlite3
```

`resultado.json` registra região, bbox, período, cenas, versão/hash/dispositivo
do modelo, estatísticas, resultados por entrada e caminhos dos artefatos. O
SQLite guarda resumos, metadata e caminhos; os rasters e PNGs ficam fora do
banco. Em pacotes Linux, os defaults são
`~/.local/share/sentinel2-mt/analises` e
`~/.local/share/sentinel2-mt/historico-analises.sqlite3`, separados dos caminhos
`data/` usados no desenvolvimento.

## Limites

As caixas do detector usam coordenadas de pixels da representação RGB. A bbox
da configuração delimita a consulta, mas não fornece sozinha geometria de
talhões nem uma conversão validada das caixas para área. Contagens ou áreas em
pixels não devem ser apresentadas como hectares.

O pipeline e seus adaptadores foram testados com fakes e pesos sintéticos. O
peso real `best.pt` agora acompanha a árvore de desenvolvimento, portanto este
estado do repositório inclui um motor agrícola funcional. Treinamento de
modelos não integra o produto. Quando o peso for substituído, seu SHA-256
aprovado deve constar no `model_metadata.json`; a aplicação carrega um snapshot
privado validado.
