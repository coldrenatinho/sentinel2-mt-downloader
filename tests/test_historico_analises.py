from contextlib import closing
import json
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
from unittest import TestCase

from sentinel2_mt.analise.historico import RepositorioHistoricoAnalises


class TestHistoricoAnalises(TestCase):
    def test_cria_banco_seguro_com_wal_e_schema_versionado(self) -> None:
        with TemporaryDirectory() as temporario:
            pasta = Path(temporario) / "historico"
            banco = pasta / "analises.sqlite3"

            RepositorioHistoricoAnalises(banco)

            self.assertEqual(stat.S_IMODE(pasta.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(banco.stat().st_mode), 0o600)
            with closing(sqlite3.connect(banco)) as conexao:
                self.assertEqual(conexao.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(conexao.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                tipos = {
                    linha[1]: linha[2]
                    for linha in conexao.execute("PRAGMA table_info(analises)").fetchall()
                }
            self.assertNotIn("BLOB", set(tipos.values()))

    def test_salva_e_recupera_json_e_caminhos_relativos(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            repositorio = RepositorioHistoricoAnalises(raiz / "db" / "historico.sqlite3", raiz)

            registro = repositorio.salvar(
                {
                    "analysis_id": "analise-001",
                    "status": "concluida",
                    "regiao": "Norte de MT",
                    "bbox": [-56.0, -13.0, -55.0, -12.0],
                    "period_start": "2025-01-01",
                    "period_end": "2025-01-31",
                    "scene_id": "S2_TESTE",
                    "model_version": "1.2.0",
                    "model_hash": "sha256:abc",
                    "summary": {"caixas": 3},
                    "metadados": {"sensor": "MSI"},
                    "input_path": raiz / "entradas" / "cena.tif",
                    "report_path": raiz / "relatorios" / "analise-001.pdf",
                }
            )

            self.assertEqual(registro.bbox, [-56.0, -13.0, -55.0, -12.0])
            self.assertEqual(registro.resumo, {"caixas": 3})
            self.assertEqual(registro.caminho_entrada, "entradas/cena.tif")
            self.assertEqual(registro.report_path, "relatorios/analise-001.pdf")
            self.assertEqual(registro.summary, {"caixas": 3})
            self.assertEqual(registro.created_at, registro.criado_em)
            with closing(sqlite3.connect(repositorio.caminho_banco)) as conexao:
                linha = conexao.execute(
                    "SELECT bbox_json, resumo_json FROM analises WHERE analysis_id = ?",
                    ("analise-001",),
                ).fetchone()
            self.assertEqual(json.loads(linha[0]), [-56.0, -13.0, -55.0, -12.0])
            self.assertEqual(json.loads(linha[1]), {"caixas": 3})

    def test_atualiza_status_sem_apagar_metadados(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            repositorio = RepositorioHistoricoAnalises(raiz / "historico" / "db.sqlite3", raiz)
            repositorio.salvar(
                {
                    "analysis_id": "a1",
                    "status": "executando",
                    "bbox": [1, 2, 3, 4],
                    "metadados": {"origem": "teste"},
                }
            )

            atualizado = repositorio.atualizar_status(
                "a1",
                "concluida",
                resumo={"caixas": 2},
                report_path="relatorios/a1.pdf",
            )

            self.assertEqual(atualizado.status, "concluida")
            self.assertEqual(atualizado.resumo, {"caixas": 2})
            self.assertEqual(atualizado.metadados, {"origem": "teste"})
            self.assertEqual(repositorio.listar(status="concluida"), [atualizado])

    def test_rejeita_caminho_que_escapa_da_raiz(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            repositorio = RepositorioHistoricoAnalises(raiz / "historico" / "db.sqlite3", raiz)

            with self.assertRaises(ValueError):
                repositorio.salvar(
                    {
                        "analysis_id": "a1",
                        "status": "erro",
                        "report_path": "../fora.pdf",
                    }
                )

    def test_valores_sao_parametrizados(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            repositorio = RepositorioHistoricoAnalises(raiz / "historico" / "db.sqlite3", raiz)
            identificador = "x'); DROP TABLE analises; --"

            repositorio.salvar({"analysis_id": identificador, "status": "concluida"})

            self.assertIsNotNone(repositorio.buscar(identificador))
            self.assertEqual(len(repositorio.listar()), 1)

    def test_rejeita_banco_em_link_simbolico(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            alvo = raiz / "alvo.sqlite3"
            alvo.write_bytes(b"")
            link = raiz / "historico.sqlite3"
            link.symlink_to(alvo)

            with self.assertRaisesRegex(ValueError, "links simbólicos"):
                RepositorioHistoricoAnalises(link, raiz)
