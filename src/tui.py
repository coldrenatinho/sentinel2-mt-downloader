from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

EMPACOTADO = bool(getattr(sys, "frozen", False))
ROOT = Path.cwd() if EMPACOTADO else Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "baixar_inpe_mt.py"
if EMPACOTADO:
    _configuracoes = (Path("/etc/sentinel2-mt/config.yaml"), Path(sys.executable).resolve().parent / "sentinel2-mt-config.yaml")
    CONFIG_PADRAO = next((caminho for caminho in _configuracoes if caminho.is_file()), _configuracoes[0])
else:
    CONFIG_PADRAO = ROOT / "config/config.yaml"

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.containers import Grid, Horizontal, VerticalScroll
    from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Select, Static
except ModuleNotFoundError as exc:
    if sys.prefix == sys.base_prefix:
        print("Preparando o ambiente virtual do projeto...", file=sys.stderr)
        raise SystemExit(subprocess.call([sys.executable, str(ROOT / "iniciar_tui.py")], cwd=ROOT)) from exc
    print(
        f"Dependência Python ausente: {exc.name}.\n"
        "Execute `python iniciar_tui.py` na raiz do projeto para criar o ambiente isolado automaticamente.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

class SentinelTUI(App):
    TITLE = "Sentinel-2 MT Downloader"
    SUB_TITLE = "Catálogo, download, análise por IA e Google Drive"

    CSS = """
    Screen {
        background: $surface;
    }

    #conteudo {
        padding: 1 2;
    }

    #titulo {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #formulario {
        grid-size: 2;
        grid-columns: 25 1fr;
        grid-gutter: 1;
        height: auto;
        margin-bottom: 1;
    }

    #formulario Label {
        height: 3;
        content-align: right middle;
    }

    #acoes {
        height: 3;
        margin-bottom: 1;
    }

    #acoes Button {
        margin-right: 1;
    }

    #log {
        height: 1fr;
        min-height: 12;
        border: round $primary;
        padding: 0 1;
    }

    #estado {
        height: 1;
        margin-bottom: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("ctrl+q", "quit", "Sair"),
        ("ctrl+l", "limpar_log", "Limpar log"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.processo: subprocess.Popen[str] | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="conteudo"):
            yield Static("Operação Sentinel-2", id="titulo")
            with Grid(id="formulario"):
                yield Label("Operação")
                yield Select(
                    [
                        ("Catalogar sem baixar", "catalogar"),
                        ("Baixar imagens", "baixar"),
                        ("Gerar dataset local", "dataset"),
                        ("Analisar região com IA", "analisar"),
                        ("Sincronizar com Google Drive", "sincronizar"),
                    ],
                    value="catalogar",
                    allow_blank=False,
                    id="operacao",
                )
                yield Label("Arquivo de configuração")
                yield Input(value=str(CONFIG_PADRAO), id="config")
                yield Label("Data inicial (AAAA-MM-DD)")
                yield Input(placeholder="Usar config.yaml", id="inicio")
                yield Label("Data final (AAAA-MM-DD)")
                yield Input(placeholder="Usar config.yaml", id="fim")
                yield Label("Máximo de cenas")
                yield Input(placeholder="Usar config.yaml; 0 = todas", id="max_itens", type="integer")
                yield Label("Tamanho dos patches")
                yield Select(
                    [("512 px", 512), ("256 px", 256)],
                    value=512,
                    allow_blank=False,
                    id="patch_size",
                )
                yield Label("Stride dos patches")
                yield Input(value="512", id="patch_stride", type="integer")
                yield Label("JSON OAuth do Google")
                yield Input(placeholder="Usar caminho do config.yaml", id="oauth_json")
                yield Label("Tamanho do lote")
                yield Input(placeholder="Usar config.yaml", id="lote", type="integer")
            yield Static("Pronto para executar.", id="estado")
            with Horizontal(id="acoes"):
                yield Button("Executar", variant="primary", id="executar")
                yield Button("Cancelar", variant="error", id="cancelar", disabled=True)
                yield Button("Limpar log", id="limpar")
                yield Button("Sair", id="sair")
            yield RichLog(id="log", wrap=True, highlight=True, markup=False)
        yield Footer()

    def action_limpar_log(self) -> None:
        self.query_one("#log", RichLog).clear()

    def on_mount(self) -> None:
        self.atualizar_campos("catalogar")

    def on_select_changed(self, evento: Select.Changed) -> None:
        if evento.select.id == "operacao" and isinstance(evento.value, str):
            self.atualizar_campos(evento.value)

    def atualizar_campos(self, operacao: str) -> None:
        sincronizacao = operacao == "sincronizar"
        for campo in ("#inicio", "#fim", "#max_itens"):
            self.query_one(campo, Input).disabled = sincronizacao
        for campo in ("#oauth_json", "#lote"):
            self.query_one(campo, Input).disabled = not sincronizacao
        usa_patches = operacao in {"dataset", "analisar"}
        self.query_one("#patch_size", Select).disabled = not usa_patches
        self.query_one("#patch_stride", Input).disabled = not usa_patches

    def montar_comando(self) -> list[str]:
        operacao = str(self.query_one("#operacao", Select).value)
        config = Path(self.query_one("#config", Input).value.strip()).expanduser()
        if not config.is_file():
            raise ValueError(f"Configuração não encontrada: {config}")

        comando = [sys.executable, "--cli", "--config", str(config)] if EMPACOTADO else [sys.executable, "-u", str(SCRIPT), "--config", str(config)]
        if operacao == "baixar":
            comando.append("--baixar")
        elif operacao in {"dataset", "analisar"}:
            stride = self.query_one("#patch_stride", Input).value.strip()
            if not stride or int(stride) <= 0:
                raise ValueError("O stride dos patches deve ser maior que zero.")
            comando.extend(
                [
                    "--analisar" if operacao == "analisar" else "--gerar-dataset",
                    "--patch-size",
                    str(self.query_one("#patch_size", Select).value),
                    "--patch-stride",
                    stride,
                ]
            )
        elif operacao == "sincronizar":
            comando.append("--sincronizar")

        inicio = self.query_one("#inicio", Input).value.strip()
        fim = self.query_one("#fim", Input).value.strip()
        max_itens = self.query_one("#max_itens", Input).value.strip()
        oauth_json = self.query_one("#oauth_json", Input).value.strip()
        lote = self.query_one("#lote", Input).value.strip()

        if operacao != "sincronizar":
            if inicio:
                comando.extend(["--inicio", inicio])
            if fim:
                comando.extend(["--fim", fim])
            if max_itens:
                if int(max_itens) < 0:
                    raise ValueError("Máximo de cenas não pode ser negativo.")
                comando.extend(["--max-itens", max_itens])
        else:
            if oauth_json:
                oauth_path = Path(oauth_json).expanduser()
                if not oauth_path.is_file():
                    raise ValueError(f"JSON OAuth não encontrado: {oauth_path}")
                comando.extend(["--oauth-json", str(oauth_path)])
            if lote:
                if int(lote) <= 0:
                    raise ValueError("O tamanho do lote deve ser maior que zero.")
                comando.extend(["--lote", lote])
        return comando

    def on_button_pressed(self, evento: Button.Pressed) -> None:
        if evento.button.id == "executar":
            if self.processo and self.processo.poll() is None:
                self.notify("Já existe uma operação em andamento.", severity="warning")
                return
            try:
                comando = self.montar_comando()
            except (TypeError, ValueError) as exc:
                self.notify(str(exc), severity="error")
                return
            log = self.query_one("#log", RichLog)
            log.write(f"$ {' '.join(comando)}")
            self.alterar_estado(True, "Iniciando operação...")
            self.executar_comando(comando)
        elif evento.button.id == "cancelar":
            if self.processo and self.processo.poll() is None:
                self.processo.terminate()
                self.query_one("#estado", Static).update("Cancelamento solicitado...")
        elif evento.button.id == "limpar":
            self.action_limpar_log()
        elif evento.button.id == "sair":
            self.exit()

    def alterar_estado(self, executando: bool, mensagem: str) -> None:
        self.query_one("#executar", Button).disabled = executando
        self.query_one("#cancelar", Button).disabled = not executando
        self.query_one("#estado", Static).update(mensagem)

    def escrever_log(self, linha: str) -> None:
        self.query_one("#log", RichLog).write(linha)

    @work(thread=True, exclusive=True, group="operacao", exit_on_error=False)
    def executar_comando(self, comando: list[str]) -> None:
        ambiente = os.environ.copy()
        ambiente["PYTHONUNBUFFERED"] = "1"
        try:
            self.processo = subprocess.Popen(
                comando,
                cwd=ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=ambiente,
            )
            self.call_from_thread(self.alterar_estado, True, "Operação em andamento...")
            if self.processo.stdout:
                for linha in self.processo.stdout:
                    self.call_from_thread(self.escrever_log, linha.rstrip())
            codigo = self.processo.wait()
            if codigo == 0:
                mensagem = "Operação concluída com sucesso."
            elif codigo < 0:
                mensagem = "Operação cancelada."
            else:
                mensagem = f"Operação encerrada com código {codigo}."
            self.call_from_thread(self.escrever_log, mensagem)
            self.call_from_thread(self.alterar_estado, False, mensagem)
        except Exception as exc:
            mensagem = f"Falha ao executar: {exc}"
            self.call_from_thread(self.escrever_log, mensagem)
            self.call_from_thread(self.alterar_estado, False, mensagem)
        finally:
            self.processo = None

    def on_unmount(self) -> None:
        if self.processo and self.processo.poll() is None:
            self.processo.terminate()


if __name__ == "__main__":
    SentinelTUI().run()
