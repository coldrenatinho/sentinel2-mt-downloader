from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping


VERSAO_ESQUEMA = 1
def _agora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _valor(objeto: object, nome: str, padrao: Any = None) -> Any:
    if isinstance(objeto, Mapping):
        return objeto.get(nome, padrao)
    return getattr(objeto, nome, padrao)


def _json_canonico(valor: Any, *, nome: str) -> str:
    if valor is None:
        valor = {} if nome != "bbox" else []
    if isinstance(valor, str):
        try:
            valor = json.loads(valor)
        except json.JSONDecodeError as erro:
            raise ValueError(f"{nome} deve ser JSON válido") from erro
    try:
        return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{nome} deve conter apenas valores serializáveis em JSON") from erro


@dataclass(frozen=True)
class RegistroHistoricoAnalise:
    analysis_id: str
    status: str
    criado_em: str = field(default_factory=_agora_utc)
    atualizado_em: str = ""
    regiao: str = ""
    bbox: Any = field(default_factory=list)
    periodo_inicio: str = ""
    periodo_fim: str = ""
    scene_id: str = ""
    modelo_versao: str = ""
    modelo_hash: str = ""
    resumo: Any = field(default_factory=dict)
    metadados: Any = field(default_factory=dict)
    caminho_entrada: str = ""
    report_path: str = ""

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def created_at(self) -> str:
        return self.criado_em

    @property
    def updated_at(self) -> str:
        return self.atualizado_em

    @property
    def summary(self) -> Any:
        return self.resumo


class RepositorioHistoricoAnalises:
    """Histórico local de análises; persiste somente metadados e caminhos relativos."""

    def __init__(self, caminho_banco: Path | str, raiz: Path | str | None = None) -> None:
        self.caminho_banco = Path(caminho_banco)
        self.raiz = Path(raiz) if raiz is not None else self.caminho_banco.parent
        self.raiz = self.raiz.resolve(strict=False)
        self._preparar_armazenamento()
        self._inicializar()

    def _preparar_armazenamento(self) -> None:
        pasta = self.caminho_banco.parent
        if self.caminho_banco.is_symlink() or any(
            ancestral.is_symlink() for ancestral in (pasta, *pasta.parents)
        ):
            raise ValueError("O histórico não pode usar links simbólicos")
        pasta_ja_existia = pasta.exists()
        pasta.mkdir(parents=True, exist_ok=True)
        if not pasta_ja_existia:
            os.chmod(pasta, 0o700)
        flags = os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descritor = os.open(self.caminho_banco, flags, 0o600)
        os.close(descritor)
        os.chmod(self.caminho_banco, 0o600)

    @contextmanager
    def _conectar(self):
        conexao = sqlite3.connect(self.caminho_banco, timeout=5.0)
        conexao.row_factory = sqlite3.Row
        conexao.execute("PRAGMA busy_timeout = 5000")
        conexao.execute("PRAGMA foreign_keys = ON")
        try:
            with conexao:
                yield conexao
        finally:
            conexao.close()

    def _inicializar(self) -> None:
        with self._conectar() as conexao:
            conexao.execute("PRAGMA journal_mode = WAL")
            versao = int(conexao.execute("PRAGMA user_version").fetchone()[0])
            if versao > VERSAO_ESQUEMA:
                raise RuntimeError(
                    f"Banco de histórico usa esquema {versao}, superior ao suportado {VERSAO_ESQUEMA}"
                )
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS analises (
                    analysis_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    criado_em TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    regiao TEXT NOT NULL DEFAULT '',
                    bbox_json TEXT NOT NULL DEFAULT '[]',
                    periodo_inicio TEXT NOT NULL DEFAULT '',
                    periodo_fim TEXT NOT NULL DEFAULT '',
                    scene_id TEXT NOT NULL DEFAULT '',
                    modelo_versao TEXT NOT NULL DEFAULT '',
                    modelo_hash TEXT NOT NULL DEFAULT '',
                    resumo_json TEXT NOT NULL DEFAULT '{}',
                    metadados_json TEXT NOT NULL DEFAULT '{}',
                    caminho_entrada TEXT NOT NULL DEFAULT '',
                    report_path TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conexao.execute(
                "CREATE INDEX IF NOT EXISTS idx_analises_atualizado_em ON analises(atualizado_em DESC)"
            )
            conexao.execute(f"PRAGMA user_version = {VERSAO_ESQUEMA}")
        os.chmod(self.caminho_banco, 0o600)

    def _caminho_relativo(self, valor: Path | str | None, *, campo: str) -> str:
        if valor is None or str(valor) == "":
            return ""
        caminho = Path(valor)
        if caminho.is_absolute():
            try:
                caminho = caminho.resolve(strict=False).relative_to(self.raiz)
            except ValueError as erro:
                raise ValueError(f"{campo} deve estar dentro da raiz do histórico") from erro
        if caminho.anchor or ".." in caminho.parts:
            raise ValueError(f"{campo} deve ser um caminho relativo sem '..'")
        return caminho.as_posix()

    def salvar(self, analise: object) -> RegistroHistoricoAnalise:
        analysis_id = str(_valor(analise, "analysis_id", "")).strip()
        if not analysis_id:
            raise ValueError("analysis_id é obrigatório")
        status = str(_valor(analise, "status", "pendente")).strip().lower()
        if not status:
            raise ValueError("status é obrigatório")
        criado_em = str(_valor(analise, "criado_em", "") or _valor(analise, "created_at", "") or _agora_utc())
        atualizado_em = str(
            _valor(analise, "atualizado_em", "") or _valor(analise, "updated_at", "") or criado_em
        )
        bbox_json = _json_canonico(_valor(analise, "bbox", []), nome="bbox")
        resumo_json = _json_canonico(
            _valor(analise, "resumo", _valor(analise, "summary", {})), nome="resumo"
        )
        metadados_json = _json_canonico(_valor(analise, "metadados", {}), nome="metadados")
        caminho_entrada = self._caminho_relativo(
            _valor(analise, "caminho_entrada", _valor(analise, "input_path", "")),
            campo="caminho_entrada",
        )
        report_path = self._caminho_relativo(
            _valor(analise, "report_path", _valor(analise, "caminho_relatorio", "")),
            campo="report_path",
        )
        valores = (
            analysis_id,
            status,
            criado_em,
            atualizado_em,
            str(_valor(analise, "regiao", _valor(analise, "region", ""))),
            bbox_json,
            str(_valor(analise, "periodo_inicio", _valor(analise, "period_start", ""))),
            str(_valor(analise, "periodo_fim", _valor(analise, "period_end", ""))),
            str(_valor(analise, "scene_id", "")),
            str(_valor(analise, "modelo_versao", _valor(analise, "model_version", ""))),
            str(_valor(analise, "modelo_hash", _valor(analise, "model_hash", ""))),
            resumo_json,
            metadados_json,
            caminho_entrada,
            report_path,
        )
        with self._conectar() as conexao:
            conexao.execute(
                """
                INSERT INTO analises (
                    analysis_id, status, criado_em, atualizado_em, regiao, bbox_json,
                    periodo_inicio, periodo_fim, scene_id, modelo_versao, modelo_hash,
                    resumo_json, metadados_json, caminho_entrada, report_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(analysis_id) DO UPDATE SET
                    status = excluded.status,
                    atualizado_em = excluded.atualizado_em,
                    regiao = excluded.regiao,
                    bbox_json = excluded.bbox_json,
                    periodo_inicio = excluded.periodo_inicio,
                    periodo_fim = excluded.periodo_fim,
                    scene_id = excluded.scene_id,
                    modelo_versao = excluded.modelo_versao,
                    modelo_hash = excluded.modelo_hash,
                    resumo_json = excluded.resumo_json,
                    metadados_json = excluded.metadados_json,
                    caminho_entrada = excluded.caminho_entrada,
                    report_path = excluded.report_path
                """,
                valores,
            )
        os.chmod(self.caminho_banco, 0o600)
        registro = self.buscar(analysis_id)
        assert registro is not None
        return registro

    registrar = salvar
    criar = salvar

    def atualizar_status(
        self,
        analysis_id: str,
        status: str,
        *,
        resumo: Any | None = None,
        report_path: Path | str | None = None,
        atualizado_em: str | None = None,
    ) -> RegistroHistoricoAnalise:
        status = status.strip().lower()
        if not status:
            raise ValueError("status é obrigatório")
        atribuicoes = ["status = ?", "atualizado_em = ?"]
        parametros: list[Any] = [status, atualizado_em or _agora_utc()]
        if resumo is not None:
            atribuicoes.append("resumo_json = ?")
            parametros.append(_json_canonico(resumo, nome="resumo"))
        if report_path is not None:
            atribuicoes.append("report_path = ?")
            parametros.append(self._caminho_relativo(report_path, campo="report_path"))
        parametros.append(analysis_id)
        with self._conectar() as conexao:
            cursor = conexao.execute(
                f"UPDATE analises SET {', '.join(atribuicoes)} WHERE analysis_id = ?",
                parametros,
            )
            if cursor.rowcount != 1:
                raise KeyError(analysis_id)
        registro = self.buscar(analysis_id)
        assert registro is not None
        return registro

    def buscar(self, analysis_id: str) -> RegistroHistoricoAnalise | None:
        with self._conectar() as conexao:
            linha = conexao.execute(
                "SELECT * FROM analises WHERE analysis_id = ?", (analysis_id,)
            ).fetchone()
        return self._converter(linha) if linha is not None else None

    obter = buscar

    def listar(self, *, status: str | None = None, limite: int | None = None) -> list[RegistroHistoricoAnalise]:
        consulta = "SELECT * FROM analises"
        parametros: list[Any] = []
        if status is not None:
            consulta += " WHERE status = ?"
            parametros.append(status.strip().lower())
        consulta += " ORDER BY atualizado_em DESC, analysis_id ASC"
        if limite is not None:
            if limite < 0:
                raise ValueError("limite não pode ser negativo")
            consulta += " LIMIT ?"
            parametros.append(limite)
        with self._conectar() as conexao:
            linhas: Iterable[sqlite3.Row] = conexao.execute(consulta, parametros).fetchall()
        return [self._converter(linha) for linha in linhas]

    @staticmethod
    def _converter(linha: sqlite3.Row) -> RegistroHistoricoAnalise:
        return RegistroHistoricoAnalise(
            analysis_id=linha["analysis_id"],
            status=linha["status"],
            criado_em=linha["criado_em"],
            atualizado_em=linha["atualizado_em"],
            regiao=linha["regiao"],
            bbox=json.loads(linha["bbox_json"]),
            periodo_inicio=linha["periodo_inicio"],
            periodo_fim=linha["periodo_fim"],
            scene_id=linha["scene_id"],
            modelo_versao=linha["modelo_versao"],
            modelo_hash=linha["modelo_hash"],
            resumo=json.loads(linha["resumo_json"]),
            metadados=json.loads(linha["metadados_json"]),
            caminho_entrada=linha["caminho_entrada"],
            report_path=linha["report_path"],
        )


# Alias curto para integrações futuras sem acoplar interfaces ao nome da implementação.
HistoricoAnalises = RepositorioHistoricoAnalises
HistoricoAnalisesSQLite = RepositorioHistoricoAnalises
