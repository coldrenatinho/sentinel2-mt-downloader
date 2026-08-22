import ast
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import TestCase

import yaml

from sentinel2_mt import __version__


ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(TestCase):
    def test_workflow_e_templates_estao_presentes(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8"))
        self.assertIn("packages", workflow["jobs"])
        self.assertEqual(workflow["jobs"]["packages"]["runs-on"], "ubuntu-22.04")
        self.assertTrue((ROOT / "packaging/arch/PKGBUILD.in").is_file())
        self.assertTrue((ROOT / "packaging/rpm/sentinel2-mt.spec").is_file())

    def test_workflow_instala_e_valida_gui(self) -> None:
        workflow = (ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8")
        self.assertIn("-r requirements-gui.txt", workflow)
        self.assertIn("libegl1", workflow)
        self.assertIn("QT_QPA_PLATFORM: offscreen", workflow)
        self.assertIn("--gui --smoke-test", workflow)

    def test_workflow_dispatch_nao_interpola_versao_em_script(self) -> None:
        workflow = yaml.safe_load((ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8"))
        etapas = workflow["jobs"]["packages"]["steps"]
        etapa_versao = next(etapa for etapa in etapas if etapa.get("name") == "Definir versão")
        scripts = "\n".join(etapa.get("run", "") for etapa in etapas)

        self.assertEqual(etapa_versao["env"]["DISPATCH_VERSION"], "${{ inputs.version }}")
        self.assertNotIn("${{ inputs.", scripts)
        self.assertIn('VERSION="$DISPATCH_VERSION"', etapa_versao["run"])

    def test_workflow_valida_wrapper_distribuido(self) -> None:
        workflow = (ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8")
        self.assertIn("./release/sentinel2-mt-wrapper.sh --version", workflow)
        self.assertIn("./release/sentinel2-mt-wrapper.sh --help", workflow)

    def test_atalho_desktop_abre_gui_sem_terminal(self) -> None:
        desktop = (ROOT / "packaging/sentinel2-mt.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=sentinel2-mt --gui", desktop)
        self.assertIn("Terminal=false", desktop)
        self.assertNotIn("Desktop Action", desktop)

    def test_pacotes_usam_wrapper_de_compatibilidade_grafica(self) -> None:
        wrapper = (ROOT / "packaging/sentinel2-mt-wrapper.sh").read_text(encoding="utf-8")
        build = (ROOT / "packaging/build_linux_packages.sh").read_text(encoding="utf-8")
        rpm = (ROOT / "packaging/rpm/sentinel2-mt.spec").read_text(encoding="utf-8")
        arch = (ROOT / "packaging/arch/PKGBUILD.in").read_text(encoding="utf-8")

        self.assertIn("LD_PRELOAD", wrapper)
        self.assertIn("--disable-gpu", wrapper)
        self.assertIn("usr/lib/sentinel2-mt/sentinel2-mt", build)
        self.assertIn("%{_prefix}/lib/sentinel2-mt/sentinel2-mt", rpm)
        self.assertIn("$pkgdir/usr/lib/sentinel2-mt/sentinel2-mt", arch)
        self.assertIn("sentinel2-mt-wrapper.sh", rpm)
        self.assertIn("sentinel2-mt-wrapper.sh", arch)

    def test_wrapper_executa_binario_adjacente_e_repassa_argumentos(self) -> None:
        with tempfile.TemporaryDirectory() as temporario:
            pasta = Path(temporario)
            wrapper = pasta / "sentinel2-mt-wrapper.sh"
            binario = pasta / "sentinel2-mt-linux-x86_64"
            shutil.copy2(ROOT / "packaging/sentinel2-mt-wrapper.sh", wrapper)
            wrapper.chmod(0o755)
            binario.write_text('#!/bin/sh\nprintf "<%s>\\n" "$@"\n', encoding="utf-8")
            binario.chmod(0o755)

            resultado = subprocess.run(
                [str(wrapper), "--area", "Cuiabá e Várzea Grande", "$(nao-executar)"],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertEqual(
            resultado.stdout.splitlines(),
            ["<--area>", "<Cuiabá e Várzea Grande>", "<$(nao-executar)>"],
        )

    def test_wrapper_rejeita_recursao_com_binario_adjacente(self) -> None:
        wrapper = (ROOT / "packaging/sentinel2-mt-wrapper.sh").read_text(encoding="utf-8")
        self.assertIn('! [ "$adjacent_binary" -ef "$0" ]', wrapper)

    def test_versao_do_workflow_acompanha_codigo(self) -> None:
        workflow = (ROOT / ".github/workflows/packages.yml").read_text(encoding="utf-8")
        self.assertIn(f'default: "{__version__}"', workflow)

    def test_configuracao_de_pacote_nao_contem_segredos(self) -> None:
        conteudo = (ROOT / "packaging/config.yaml").read_text(encoding="utf-8")
        self.assertNotIn("client_secret", conteudo)
        self.assertNotIn("client_id", conteudo)

    def test_spec_resolve_entrypoint_a_partir_da_pasta_packaging(self) -> None:
        caminho_spec = ROOT / "packaging/sentinel2-mt.spec"
        arvore = ast.parse(caminho_spec.read_text(encoding="utf-8"))
        atribuicao_root = next(
            no
            for no in arvore.body
            if isinstance(no, ast.Assign)
            and any(isinstance(alvo, ast.Name) and alvo.id == "ROOT" for alvo in no.targets)
        )
        expressao = ast.Expression(body=atribuicao_root.value)
        raiz_calculada = eval(
            compile(expressao, str(caminho_spec), "eval"),
            {"Path": Path, "SPECPATH": str(caminho_spec.parent)},
        )

        self.assertEqual(raiz_calculada, ROOT)
        self.assertTrue((raiz_calculada / "src/main.py").is_file())

    def test_spec_inclui_pyside6_na_distribuicao(self) -> None:
        conteudo = (ROOT / "packaging/sentinel2-mt.spec").read_text(encoding="utf-8")
        arvore = ast.parse(conteudo)
        chamada = next(
            no
            for no in ast.walk(arvore)
            if isinstance(no, ast.Call)
            and isinstance(no.func, ast.Name)
            and no.func.id == "Analysis"
        )
        argumento = next(item for item in chamada.keywords if item.arg == "excludes")
        exclusoes = ast.literal_eval(argumento.value)

        self.assertNotIn("PySide6", exclusoes)
        self.assertIn("PyQt6", exclusoes)

    def test_build_arch_respeita_extensao_configurada_pelo_makepkg(self) -> None:
        conteudo = (ROOT / "packaging/build_arch_package.sh").read_text(encoding="utf-8")
        self.assertIn("makepkg --packagelist", conteudo)
        self.assertNotIn('*.pkg.tar.zst', conteudo)

    def test_runtime_ia_e_modelo_entram_no_bundle(self) -> None:
        requisitos = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        spec = (ROOT / "packaging/sentinel2-mt.spec").read_text(encoding="utf-8")
        self.assertIn("ultralytics", requisitos)
        self.assertIn("matplotlib", requisitos)
        self.assertIn('"torch"', spec)
        self.assertIn('"ultralytics"', spec)
        self.assertIn("sentinel2_mt/analise/models", spec)

    def test_configs_de_desenvolvimento_e_pacote_expoem_analise(self) -> None:
        desenvolvimento = yaml.safe_load((ROOT / "config/config.yaml").read_text(encoding="utf-8"))
        pacote = yaml.safe_load((ROOT / "packaging/config.yaml").read_text(encoding="utf-8"))
        self.assertEqual(set(desenvolvimento["analise"]), set(pacote["analise"]))
        self.assertEqual(
            desenvolvimento["analise"]["modelo"], pacote["analise"]["modelo"]
        )
