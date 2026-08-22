from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .configuracao import ConfiguracaoProjeto
from .google_drive import SincronizadorGoogleDrive
from .analise.servico import OpcoesAnalise, ServicoAnaliseAgricola
from .servico import OpcoesColeta, ServicoSentinel2


EMPACOTADO = bool(getattr(sys, "frozen", False))
ROOT = Path.home() if EMPACOTADO else Path(__file__).resolve().parents[2]
CONFIG_SISTEMA = Path("/etc/sentinel2-mt/config.yaml")


def configuracao_padrao() -> Path:
    if "SENTINEL2_CONFIG" in os.environ:
        return Path(os.environ["SENTINEL2_CONFIG"]).expanduser()
    if not EMPACOTADO:
        return ROOT / "config/config.yaml"
    candidatos = (CONFIG_SISTEMA, Path(sys.executable).resolve().parent / "sentinel2-mt-config.yaml")
    return next((caminho for caminho in candidatos if caminho.is_file()), CONFIG_SISTEMA)


CONFIG_PADRAO = configuracao_padrao()


class AplicacaoCLI:
    def criar_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description="Downloader Sentinel-2 MT com filtro automático de nuvens via SCL.")
        parser.add_argument("--version", action="version", version=f"sentinel2-mt {__version__}")
        parser.add_argument("--config", type=Path, default=CONFIG_PADRAO)
        parser.add_argument("--inicio")
        parser.add_argument("--fim")
        parser.add_argument("--max-itens", type=int, help="Quantidade de cenas aprovadas; 0 = todas.")
        parser.add_argument("--baixar", action="store_true")
        parser.add_argument(
            "--gerar-dataset",
            action="store_true",
            help="Gera patches; sem --baixar, reutiliza as cenas GeoTIFF locais.",
        )
        parser.add_argument("--patch-size", type=int, choices=(256, 512), help="Tamanho do patch em pixels.")
        parser.add_argument("--patch-stride", type=int, help="Passo entre patches em pixels.")
        parser.add_argument("--sincronizar", action="store_true", help="Sincroniza imagens com a API do Google Drive.")
        parser.add_argument(
            "--analisar",
            action="store_true",
            help="Baixa/processa as cenas e executa a análise agrícola local.",
        )
        parser.add_argument("--oauth-json", type=Path, help="Arquivo JSON OAuth; sobrescreve a configuração.")
        parser.add_argument("--lote", type=int, help="Sobrescreve o tamanho do lote de sincronização.")
        return parser

    def executar(self, argv: list[str] | None = None) -> int:
        args = self.criar_parser().parse_args(argv)
        try:
            config = ConfiguracaoProjeto.carregar(args.config, raiz=ROOT)
            if args.sincronizar and args.analisar:
                raise ValueError("--sincronizar e --analisar não podem ser usados juntos")
            if args.sincronizar:
                SincronizadorGoogleDrive(config).sincronizar(oauth_path=args.oauth_json, tamanho_lote=args.lote)
                return 0

            if args.analisar:
                resultado = ServicoAnaliseAgricola(config).executar(
                    OpcoesAnalise(
                        inicio=args.inicio,
                        fim=args.fim,
                        max_itens=args.max_itens,
                        patch_size=args.patch_size,
                        patch_stride=args.patch_stride,
                    )
                )
                caminho = Path(resultado.caminho_resultado)
                try:
                    caminho = caminho.relative_to(config.raiz)
                except ValueError:
                    caminho = Path(caminho.name)
                print(f"[ANALISE_RESULTADO] {caminho.as_posix()}")
                return 0

            opcoes = OpcoesColeta(
                baixar_arquivos=args.baixar,
                inicio=args.inicio,
                fim=args.fim,
                max_itens=args.max_itens,
                gerar_dataset=(
                    args.gerar_dataset
                    or args.patch_size is not None
                    or args.patch_stride is not None
                ),
                patch_size=args.patch_size,
                patch_stride=args.patch_stride,
            )
            resumo = ServicoSentinel2(config).executar(opcoes)
            return 0 if resumo.erros == 0 else 2
        except (FileNotFoundError, ValueError) as exc:
            print(f"[ERRO] {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"[ERRO] Falha inesperada: {exc}", file=sys.stderr)
            return 1


def main(argv: list[str] | None = None) -> int:
    return AplicacaoCLI().executar(argv)
