# Empacotamento Linux

O workflow `.github/workflows/packages.yml` gera um executável autocontido com
PyInstaller. A GUI PySide6 é a interface principal desses artefatos; TUI e CLI
permanecem incluídas no mesmo executável. O workflow produz os formatos:

- Debian/Ubuntu: `.deb`;
- Fedora/RHEL/openSUSE: `.rpm`;
- Arch Linux: `.pkg.tar.zst` e `PKGBUILD`;
- binário Linux x86_64 e `SHA256SUMS`.

## Publicação

O código declara a versão em `src/sentinel2_mt/__init__.py`. A tag deve usar a
mesma versão com o prefixo `v`:

```bash
git tag -a v2.0.0 -m "release: v2.0.0"
git push origin v2.0.0
```

O push da tag inicia o workflow e publica ou atualiza a GitHub Release. Uma
execução manual em **Actions → Pacotes Linux → Run workflow** gera os artefatos
para teste, mas não cria uma Release.

## Instalação dos artefatos

```bash
# Debian/Ubuntu
sudo apt install ./sentinel2-mt-downloader_2.0.0_amd64.deb

# Fedora/RHEL
sudo dnf install ./sentinel2-mt-downloader-2.0.0-1.x86_64.rpm

# Arch Linux
sudo pacman -U ./sentinel2-mt-downloader-bin-2.0.0-1-x86_64.pkg.tar.zst
```

Em builds locais, a extensão depende de `PKGEXT` na configuração do Arch.
Alguns ambientes geram `sentinel2-mt-downloader-bin-2.0.0-1-x86_64.pkg.tar`
em vez de `.pkg.tar.zst`; esse arquivo também é um pacote válido e pode ser
instalado diretamente com `sudo pacman -U caminho/do/pacote.pkg.tar`.

O `PKGBUILD` publicado também pode ser colocado em uma pasta vazia e instalado
com `makepkg -si`.

## Execução

Abra **Sentinel-2 MT Downloader** pelo menu de aplicativos ou use:

```bash
sentinel2-mt                  # GUI principal
sentinel2-mt --gui            # GUI explícita
sentinel2-mt --tui            # interface de terminal
sentinel2-mt --cli --help     # automação por linha de comando
sentinel2-mt --cli --analisar # coleta, patches e análise agrícola local
```

O atalho desktop não abre uma janela de terminal. Para usar a TUI, abra um
terminal e execute `sentinel2-mt --tui`.

Os pacotes instalam um lançador de compatibilidade que prioriza a `libstdc++`
do sistema e desativa a aceleração do QtWebEngine. Isso evita conflitos entre
as bibliotecas incluídas pelo PyInstaller e drivers gráficos mais recentes.

## Runtime e modelo de análise

O bundle coleta Ultralytics, Torch e Matplotlib para inferência e relatórios. A
spec inclui `sentinel2_mt/analise/models` quando o diretório existe, mas o peso
`agricultura.pt` não está no repositório atual: portanto, os artefatos gerados a
partir deste estado não têm inferência real pronta para uso. Para distribuir um
modelo aprovado, ele deve estar em
`src/sentinel2_mt/analise/models/agricultura.pt` antes do build; mantenha ao lado
o `model_metadata.json` correspondente com o SHA-256 obrigatório. O build falha
se o peso presente não coincidir com o manifesto.

Esse caminho é de desenvolvimento/build e não deve ser confundido com um
diretório gravável instalado. Em execução empacotada, o modelo é lido do bundle
construído. Consulte [../docs/modelo-ia.md](../docs/modelo-ia.md) para o contrato
do arquivo e as limitações atuais.

## Build local

Instale as dependências da GUI e do build antes de gerar
`dist/sentinel2-mt`. Depois, os pacotes DEB e RPM podem ser criados com:

```bash
python -m pip install -r requirements-gui.txt -r requirements-build.txt
python -m PyInstaller --noconfirm --clean packaging/sentinel2-mt.spec
packaging/build_linux_packages.sh 2.0.0
```

São necessários `dpkg-deb` e `rpmbuild`. O pacote Arch é construído no workflow
dentro da imagem `archlinux:base-devel`.
