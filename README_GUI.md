# Interface gráfica integrada

O projeto inclui uma central desktop em Qt for Python (PySide6) para configurar,
executar e acompanhar o Sentinel-2 MT Downloader.

## Como executar

```bash
python iniciar_gui.py
```

O inicializador cria ou reaproveita a `.venv` e instala as dependências gráficas
sem modificar os pacotes Python do sistema. Para apenas preparar o ambiente:

```bash
python iniciar_gui.py --setup-only
```

## O que ela faz

- navegação por visão geral, área, qualidade, Google Drive, análise, histórico e
  configuração;
- mapa OpenStreetMap com seleção da bounding box usando `Shift + arrastar`;
- execução integrada de catalogação, download, dataset, análise e sincronização;
- log em tempo real, estado da operação e cancelamento seguro;
- escolha do JSON OAuth e sincronização em lotes;
- geração e revisão visual do `config.yaml`;
- configuração de patches 256/512, stride, nuvem e dados válidos mínimos;
- geração do dataset junto ao download ou a partir das cenas locais;
- perfis locais de região em SQLite, sem armazenar OAuth ou tokens;
- abertura da pasta de imagens e visualização dos previews RGB.

## Análise agrícola na GUI

Em **Dados e qualidade**, configure o modelo, confiança mínima, IoU máximo,
tamanho da inferência, pasta de análises, histórico, geração do PDF e limite de
imagens. Na visão geral, selecione **Analisar região com IA**.

A GUI salva o YAML e inicia a CLI em um `QProcess`. A CLI baixa e processa as
cenas com `ServicoSentinel2`, gera patches científicos multibanda e suas
representações RGB, aplica `DetectorAgricola` somente aos PNGs RGB aprovados,
calcula estatísticas, grava overlays e `resultado.json`, gera o PDF opcional e
atualiza o histórico SQLite. A linha `[ANALISE_RESULTADO]` emitida pela CLI
permite que a GUI abra o JSON e mostre contagens por classe, confianças, imagem
original, overlay e dispositivo usado.

O peso esperado na execução pelo código-fonte é
`src/sentinel2_mt/analise/models/agricultura.pt`. O arquivo não acompanha o
repositório atual. Sem ele, a operação informa que o modelo é inexistente e não
executa inferência. Ultralytics e Torch são necessários para o detector;
Matplotlib é necessário quando o relatório PDF está habilitado. Consulte
[docs/modelo-ia.md](docs/modelo-ia.md) antes de substituir o peso.

O histórico guarda metadados e caminhos, não os GeoTIFFs. As caixas e contagens
da tela não representam área agrícola: uma bbox seleciona a região de consulta,
mas, sem escala e geometria georreferenciada validadas para as detecções, não é
correto converter caixas ou pixels em hectares.

## Observação

O mapa é carregado somente ao abrir **Área e período**. A biblioteca Leaflet é
buscada no unpkg e, se necessário, no jsDelivr; durante a inicialização a GUI
mostra **Carregando mapa...** e mantém uma mensagem visível se a biblioteca ou
o documento não responder. Para tentar novamente, saia da página e abra-a de
novo. Sem conexão, ou se apenas os tiles do OpenStreetMap falharem, o mapa pode
ficar indisponível ou sem fundo, mas as quatro coordenadas continuam editáveis
manualmente.

O token é criado automaticamente no primeiro login e não deve ser versionado.
Depois do consentimento, o callback local exibe uma página responsiva com o
estado real da autenticação e orientação para retornar à sincronização.

### Erro 403 `access_denied` no Google

O JSON OAuth identifica um projeto do Google Cloud. Quando esse projeto está com
o status **Testing**, o Google permite o login apenas das contas cadastradas em
**Google Auth Platform → Audience → Test users**. O proprietário do projeto deve
adicionar ali o mesmo e-mail escolhido no navegador. Não é necessário gerar
outro JSON depois dessa liberação.

O login sempre exibe o seletor de contas. Escolha exatamente o e-mail incluído
em **Test users**; estar conectado a outra conta Google no navegador não concede
acesso ao projeto.

Se o navegador informar que `localhost` recusou a conexão, não recarregue uma
aba antiga: o endereço usa uma porta temporária que só existe enquanto a
sincronização está aguardando o login. Volte à GUI, cancele a operação se ainda
estiver ativa e execute a sincronização novamente. O callback atual usa
explicitamente `127.0.0.1` para evitar incompatibilidade entre IPv4 e IPv6.

Essa restrição é aplicada pelo Google antes de o programa receber o token e não
pode ser removida pelo código local. Para distribuição pública, o proprietário
deve publicar/verificar o aplicativo. Consulte a
[documentação oficial sobre audiência e usuários de teste](https://support.google.com/cloud/answer/15549945).

O projeto solicita apenas `https://www.googleapis.com/auth/drive.file`. Se a URL
de autorização ainda mostrar `https://www.googleapis.com/auth/drive`, feche a
instância antiga da GUI e abra novamente com `python iniciar_gui.py`.

## Dataset na GUI

Em **Dados e qualidade**, a GUI expõe as bandas, o limite global da cena, a
geração do dataset, tamanho/stride dos patches, limite de nuvem por patch,
percentual mínimo de dados válidos e faixa fixa do RGB PNG. A GUI expõe essa
faixa fixa; `dataset.rgb.metodo`, percentis, caminhos e toggles avançados
permanecem configuráveis pela edição externa do YAML.

Na visão geral, **Gerar dataset das cenas locais** executa o pipeline sem novo
download. A operação **Baixar imagens aprovadas** também gera patches quando
**Gerar dataset após o download** estiver marcado.

O visualizador da GUI pode abrir JPEG ou PNG, mas isso não altera a hierarquia
de dados: os GeoTIFFs originais são a fonte científica, os GeoTIFFs multibanda
são os recortes científicos, o `rgb.png` é a representação 8-bit usada pelo
detector e o JPEG é somente preview. O overlay também é um PNG de visualização;
ele não sobrescreve o patch RGB nem o GeoTIFF multibanda.

A sincronização Google Drive da GUI percorre `download.pasta`. Artefatos em
`dataset.pasta`, PNG, JSON e `patches.csv` não são sincronizados por padrão.

## Legibilidade e validação

A interface usa a paleta Qt Fusion para não herdar combinações ilegíveis do
tema claro ou escuro do sistema. Campos, menus, calendários, logs, botões e
textos auxiliares usam pares de cores com contraste WCAG AA de pelo menos
`4.5:1`.

Para executar os testes de contraste, navegação, perfis, YAML, subprocessos e
sincronização simulada:

```bash
.venv/bin/python -m unittest discover -v
```
