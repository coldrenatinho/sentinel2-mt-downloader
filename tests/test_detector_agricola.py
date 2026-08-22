from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PIL import Image

from sentinel2_mt import __version__
from sentinel2_mt.analise import DetectorAgricola, ResultadoDeteccao, resolver_caminho_modelo


class TensorFake:
    def __init__(self, valores) -> None:
        self.valores = valores

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self.valores


class CaixasFake:
    xyxy = TensorFake([[2, 3, 14, 15], [5, 6, 18, 19]])
    conf = TensorFake([0.91, 0.72])
    cls = TensorFake([0, 1])


class ResultadoFake:
    boxes = CaixasFake()
    names = {0: "lavoura", 1: "pivô"}


class ModeloFake:
    names = ResultadoFake.names

    def __init__(self) -> None:
        self.chamadas = []

    def predict(self, **kwargs):
        self.chamadas.append(kwargs)
        return [ResultadoFake()]


class TestDetectorAgricola(TestCase):
    def _arquivos(self, raiz: Path) -> tuple[Path, Path, str]:
        modelo = raiz / "modelos" / "agricola.pt"
        modelo.parent.mkdir()
        modelo.write_bytes(b"pesos-sinteticos")
        imagem = raiz / "entrada.png"
        Image.new("RGB", (24, 20), "white").save(imagem)
        return modelo, imagem, hashlib.sha256(modelo.read_bytes()).hexdigest()

    def test_inferencia_lazy_converte_resultado_e_carrega_modelo_uma_vez(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            modelo_path, imagem, hash_modelo = self._arquivos(raiz)
            modelo_fake = ModeloFake()
            cargas = []

            def fabrica(caminho: str):
                cargas.append(caminho)
                return modelo_fake

            detector = DetectorAgricola(
                modelo_path,
                sha256_modelo=hash_modelo.upper(),
                versao_modelo="culturas-2026.1",
                dispositivo="cpu",
                raizes_confiaveis=[raiz],
                fabrica_modelo=fabrica,
            )
            self.assertFalse(detector.modelo_carregado)
            bytes_aprovados = modelo_path.read_bytes()
            modelo_path.write_bytes(b"substituto-nao-aprovado")

            resultado = detector.detectar(imagem, nuvens_pct=12.5)
            detector.detectar(imagem)

            self.assertTrue(detector.modelo_carregado)
            self.assertEqual(len(cargas), 1)
            self.assertNotEqual(cargas[0], str(modelo_path))
            self.assertEqual(Path(cargas[0]).read_bytes(), bytes_aprovados)
            self.assertEqual(resultado.contagem, 2)
            self.assertEqual(resultado.deteccoes[0].classe, "lavoura")
            self.assertEqual(resultado.deteccoes[0].bbox, (2.0, 3.0, 14.0, 15.0))
            self.assertNotIsInstance(resultado.deteccoes[0], ResultadoFake)
            self.assertEqual(resultado.modelo.sha256, hash_modelo)
            self.assertEqual(resultado.modelo.versao, "culturas-2026.1")
            self.assertEqual(resultado.modelo.dispositivo, "cpu")
            self.assertEqual(resultado.modelo.classes, {0: "lavoura", 1: "pivô"})
            self.assertEqual(resultado.versao, __version__)
            self.assertEqual(resultado.sha256_entrada, hashlib.sha256(imagem.read_bytes()).hexdigest())
            self.assertEqual((resultado.largura, resultado.altura), (24, 20))
            self.assertEqual(modelo_fake.chamadas[0]["device"], "cpu")

    def test_auto_seleciona_gpu_sem_importar_torch_quando_injetado(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            modelo_path, imagem, _ = self._arquivos(raiz)
            modelo_fake = ModeloFake()
            detector = DetectorAgricola(
                modelo_path,
                raizes_confiaveis=[raiz],
                fabrica_modelo=lambda _: modelo_fake,
                disponibilidade_cuda=lambda: True,
            )

            resultado = detector.detectar(imagem)

            self.assertEqual(resultado.modelo.dispositivo, "cuda:0")
            self.assertEqual(modelo_fake.chamadas[0]["device"], "cuda:0")

    def test_overlay_pillow_e_copia_sem_alterar_original(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            modelo_path, imagem, _ = self._arquivos(raiz)
            detector = DetectorAgricola(
                modelo_path,
                dispositivo="cpu",
                raizes_confiaveis=[raiz],
                fabrica_modelo=lambda _: ModeloFake(),
            )
            resultado = detector.detectar(imagem)
            original = Image.new("RGB", (24, 20), "white")

            overlay = detector.desenhar_overlay(original, resultado, cor=(255, 0, 0))

            self.assertEqual(original.getpixel((2, 3)), (255, 255, 255))
            self.assertEqual(overlay.getpixel((2, 3)), (255, 0, 0))

    def test_rejeita_url_extensao_diretorio_escape_symlink_e_hash_incorreto(self) -> None:
        with TemporaryDirectory() as temporario, TemporaryDirectory() as externo:
            raiz = Path(temporario)
            modelo_path, _, _ = self._arquivos(raiz)
            fora = Path(externo) / "fora.pt"
            fora.write_bytes(b"fora")
            link = raiz / "link.pt"
            link.symlink_to(modelo_path)
            diretorio = raiz / "diretorio.pt"
            diretorio.mkdir()

            casos = (
                lambda: resolver_caminho_modelo("https://host/modelo.pt", [raiz]),
                lambda: resolver_caminho_modelo(raiz / "modelo.onnx", [raiz]),
                lambda: resolver_caminho_modelo(fora, [raiz]),
                lambda: resolver_caminho_modelo(link, [raiz]),
                lambda: resolver_caminho_modelo(diretorio, [raiz]),
                lambda: DetectorAgricola(
                    modelo_path,
                    sha256_modelo="0" * 64,
                    raizes_confiaveis=[raiz],
                ),
            )
            for caso in casos:
                with self.subTest(caso=caso), self.assertRaises(ValueError):
                    caso()

    def test_resolve_caminho_relativo_dentro_da_raiz_confiavel(self) -> None:
        with TemporaryDirectory() as temporario:
            raiz = Path(temporario)
            modelo_path, _, _ = self._arquivos(raiz)

            resolvido = resolver_caminho_modelo("modelos/agricola.pt", [raiz])

            self.assertEqual(resolvido, modelo_path)
