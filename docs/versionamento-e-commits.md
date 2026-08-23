# Versionamento e padrão de commits

Este projeto usa Versionamento Semântico (SemVer) para releases e Conventional
Commits para manter o histórico legível e permitir a geração futura de notas de
versão automatizadas.

## Versões

Uma versão estável usa o formato `MAJOR.MINOR.PATCH`, por exemplo `1.4.2`:

- `MAJOR`: mudança incompatível com versões anteriores;
- `MINOR`: funcionalidade nova e compatível;
- `PATCH`: correção compatível, sem funcionalidade nova relevante.

A tag Git correspondente recebe o prefixo `v`: a versão `1.4.2` é publicada
como `v1.4.2`. O valor da tag, sem o `v`, deve ser idêntico a `__version__` em
`src/sentinel2_mt/__init__.py`.

Quando o projeto passar a publicar versões de pré-lançamento, elas devem usar
os sufixos SemVer:

- `v1.1.0-alpha.1`: validação inicial e potencialmente instável;
- `v1.1.0-beta.1`: funcionalidade completa, ainda em testes;
- `v1.1.0-rc.1`: candidata à versão estável.

O workflow de pacotes aceita releases estáveis e pré-releases no formato
`vX.Y.Z`, `vX.Y.Z-beta.1`, `vX.Y.Z-rc.1` e variantes equivalentes. O processo
de empacotamento normaliza internamente o formato quando necessário para DEB,
RPM e Arch.

Não reutilize nem mova uma tag já publicada. Quando uma release precisar de
correção, publique uma nova versão `PATCH`.

## Commits

Use o formato:

```text
tipo(escopo opcional): descrição curta no imperativo
```

Tipos aceitos:

| Tipo | Uso |
| --- | --- |
| `feat` | Nova funcionalidade; normalmente incrementa `MINOR` |
| `fix` | Correção de defeito; normalmente incrementa `PATCH` |
| `docs` | Alteração somente de documentação |
| `test` | Inclusão ou ajuste de testes |
| `refactor` | Reestruturação sem mudar comportamento externo |
| `perf` | Melhoria de desempenho |
| `build` | Build, dependências e empacotamento |
| `ci` | Workflows e automação de integração contínua |
| `chore` | Manutenção sem impacto funcional direto |
| `style` | Formatação sem mudança de comportamento |
| `revert` | Reversão de um commit anterior |

Exemplos:

```text
feat(sync): dividir uploads do Drive em lotes
fix(oauth): manter callback ativo até concluir autenticação
docs: documentar instalação do pacote RPM
build(packaging): incluir arquivo desktop no pacote Arch
```

A descrição deve ser objetiva, começar com letra minúscula e não terminar com
ponto. Evite commits genéricos como `ajustes`, `mudanças` ou `correções`.

### Mudanças incompatíveis

Uma quebra de compatibilidade incrementa `MAJOR` e deve ser indicada por `!`
após o tipo ou escopo, com detalhes no rodapé `BREAKING CHANGE`:

```text
feat(config)!: substituir chaves antigas de sincronização

BREAKING CHANGE: sincronizacao.rclone foi removida e substituída pela seção
sincronizacao.google_drive.
```

## Branches

Use nomes curtos no formato `tipo/descricao`:

```text
feat/gui-mapa
fix/oauth-callback
docs/versionamento
release/v1.0.0
```

Cada branch deve tratar de um objetivo coeso. Mudanças sem relação devem ficar
em branches e Pull Requests separados.

## Processo de release

1. Confirme que a branch de release parte da `main` atualizada.
2. Defina a nova versão em `src/sentinel2_mt/__init__.py`.
3. Atualize exemplos e documentação que exibem a versão corrente.
4. Execute a suíte de testes com Qt em modo offscreen.
5. Faça o commit de preparação: `chore(release): preparar vX.Y.Z`.
6. Integre a alteração na `main` e confirme o CI.
7. Crie uma tag anotada no commit aprovado.
8. Envie a tag e acompanhe o workflow **Pacotes Linux**.
9. Confira os arquivos, checksums e notas da GitHub Release.

Se o pacote Arch exceder 2 GB, ele continua disponível no artifact do
workflow, mas não entra no GitHub Release; a nota publicada aponta esse fato
explicitamente.

Comandos da etapa de publicação:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -v
git tag -a vX.Y.Z-beta.1 -m "release: vX.Y.Z-beta.1"
git push origin vX.Y.Z-beta.1
```

O workflow recusa uma tag quando a versão declarada no código não corresponde
ao nome da tag. Uma execução disparada por tag publica o binário e os pacotes
DEB, RPM e Arch; uma execução manual cria apenas artefatos temporários para
validação.
