from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any


def normalizar_bbox(bbox: list[float]) -> list[float]:
    """Normaliza coordenadas desenhadas em qualquer direção na interface."""
    if len(bbox) != 4:
        raise ValueError(
            "A bounding box deve conter exatamente 4 valores: "
            "[oeste, sul, leste, norte]."
        )

    oeste, sul, leste, norte = (float(valor) for valor in bbox)
    if not all(math.isfinite(valor) for valor in (oeste, sul, leste, norte)):
        raise ValueError("A bounding box deve conter somente coordenadas finitas.")
    if not all(-180 <= valor <= 180 for valor in (oeste, leste)):
        raise ValueError("Longitudes devem estar entre -180 e 180 graus.")
    if not all(-90 <= valor <= 90 for valor in (sul, norte)):
        raise ValueError("Latitudes devem estar entre -90 e 90 graus.")
    oeste, leste = sorted((oeste, leste))
    sul, norte = sorted((sul, norte))
    if oeste == leste or sul == norte:
        raise ValueError("A bounding box deve respeitar oeste < leste e sul < norte.")
    return [oeste, sul, leste, norte]


def montar_argumentos_operacao(
    operacao: str,
    config: str | Path,
    *,
    inicio: str = "",
    fim: str = "",
    max_itens: int | None = None,
    oauth_json: str = "",
    tamanho_lote: int | None = None,
    patch_size: int | None = None,
    patch_stride: int | None = None,
) -> list[str]:
    """Traduz o formulário da GUI para argumentos da CLI oficial."""
    if operacao not in {"catalogar", "baixar", "dataset", "analisar", "sincronizar"}:
        raise ValueError(f"Operação desconhecida: {operacao}")

    argumentos = ["--config", str(Path(config).expanduser())]
    if operacao == "baixar":
        argumentos.append("--baixar")
    elif operacao == "dataset":
        argumentos.append("--gerar-dataset")
    elif operacao == "analisar":
        argumentos.append("--analisar")
    elif operacao == "sincronizar":
        argumentos.append("--sincronizar")

    if operacao != "sincronizar":
        if inicio:
            argumentos.extend(["--inicio", inicio])
        if fim:
            argumentos.extend(["--fim", fim])
        if max_itens is not None:
            if max_itens < 0:
                raise ValueError("A quantidade máxima de cenas não pode ser negativa.")
            argumentos.extend(["--max-itens", str(max_itens)])
        if operacao in {"dataset", "analisar"} and patch_size is not None:
            if patch_size not in {256, 512}:
                raise ValueError("O tamanho do patch deve ser 256 ou 512 pixels.")
            argumentos.extend(["--patch-size", str(patch_size)])
        if operacao in {"dataset", "analisar"} and patch_stride is not None:
            if patch_stride <= 0:
                raise ValueError("O stride do patch deve ser positivo.")
            argumentos.extend(["--patch-stride", str(patch_stride)])
    else:
        if oauth_json and not oauth_json.startswith("${"):
            oauth = Path(oauth_json).expanduser()
            if not oauth.is_file():
                raise FileNotFoundError(f"JSON OAuth não encontrado: {oauth}")
            argumentos.extend(["--oauth-json", str(oauth)])
        if tamanho_lote is not None:
            if tamanho_lote <= 0:
                raise ValueError("O tamanho do lote deve ser maior que zero.")
            argumentos.extend(["--lote", str(tamanho_lote)])
    return argumentos


class LocalConfigStore:
    """Persistência local dos perfis de região; não armazena tokens OAuth."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conectar(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(self.db_path)
        conexao.row_factory = sqlite3.Row
        return conexao

    def _inicializar(self) -> None:
        with closing(self._conectar()) as conexao, conexao:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS configuracoes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome_regiao TEXT NOT NULL,
                    uf TEXT,
                    bbox TEXT NOT NULL,
                    colecao TEXT,
                    payload TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def salvar(self, dados: dict[str, Any]) -> int:
        nome = str(dados.get("nome_regiao") or "Região salva").strip()
        bbox = json.dumps(normalizar_bbox(dados.get("bbox", [-61.65, -18.05, -50.20, -7.30])))

        # Credenciais e tokens não pertencem aos perfis locais de região.
        payload = dict(dados)
        payload.pop("oauth_json", None)
        payload.pop("token_json", None)

        with closing(self._conectar()) as conexao, conexao:
            cursor = conexao.execute(
                """
                INSERT INTO configuracoes (nome_regiao, uf, bbox, colecao, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    nome or "Região salva",
                    dados.get("uf", "MT"),
                    bbox,
                    dados.get("colecao", "S2-16D-2"),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def listar(self) -> list[dict[str, Any]]:
        with closing(self._conectar()) as conexao:
            linhas = conexao.execute(
                """
                SELECT id, nome_regiao, uf, bbox, colecao, payload, created_at
                FROM configuracoes
                ORDER BY id DESC
                """
            ).fetchall()
        return [dict(linha) for linha in linhas]

    def listar_por_uf(self) -> dict[str, list[dict[str, Any]]]:
        agrupado: dict[str, list[dict[str, Any]]] = {}
        for perfil in self.listar():
            uf = (perfil.get("uf") or "GERAL").strip().upper() or "GERAL"
            agrupado.setdefault(uf, []).append(perfil)
        return dict(sorted(agrupado.items()))

    def carregar(self, item_id: int) -> dict[str, Any] | None:
        with closing(self._conectar()) as conexao:
            linha = conexao.execute(
                """
                SELECT id, nome_regiao, uf, bbox, colecao, payload, created_at
                FROM configuracoes
                WHERE id = ?
                """,
                (item_id,),
            ).fetchone()
        return dict(linha) if linha else None

    def excluir(self, item_id: int) -> None:
        with closing(self._conectar()) as conexao, conexao:
            conexao.execute("DELETE FROM configuracoes WHERE id = ?", (item_id,))

    def listar_presets_por_uf(self) -> dict[str, list[dict[str, Any]]]:
        return self.listar_por_uf()

    # Compatibilidade com a primeira implementação local da GUI.
    def salvar_configuracao(self, dados: dict[str, Any]) -> int:
        return self.salvar(dados)

    def listar_configuracoes(self) -> list[dict[str, Any]]:
        return self.listar()

    def carregar_por_id(self, item_id: int) -> dict[str, Any] | None:
        return self.carregar(item_id)

    def limpar(self) -> None:
        with closing(self._conectar()) as conexao, conexao:
            conexao.execute("DELETE FROM configuracoes")
