# Liberty Office

Portal web self-hosted com 13 editores integrados, Drive privado, administração de contas e MFA obrigatório. Inglês é o idioma padrão; selecione português brasileiro na interface. **Versão 0.2.0-rc.1.**

**Acessar:** [office.securityops.co](https://office.securityops.co) · [office.securityops.com.br](https://office.securityops.com.br) · [Experimentar a demonstração](https://office.securityops.co/demo). [English documentation](README.md).

![Liberty Office: catálogo de aplicativos](docs/screenshots/liberty-desktop.png)

A demonstração é identificada na tela, não aceita uploads e usa uma origem separada dos editores privados. Os arquivos de demonstração não são gravados no Drive. O modo leve de texto permite escrever sem WebGL; ele não oferece a fidelidade DOCX do editor completo.

No modo leve, TXT e Markdown são texto puro e não preservam a formatação visual.
Use HTML para exportar formatação básica. HTML importado vira texto inerte,
preservando quebras e limites de blocos; seu conteúdo nunca é executado.

<details><summary>Edição nativa e tela pequena</summary>

![Editor WordCraft nativo](docs/screenshots/liberty-word-native.png)

![Editor de texto leve do Liberty](docs/screenshots/liberty-word-lite.png)

![Liberty Office em celular](docs/screenshots/liberty-mobile.png)

</details>

## Deploy com Docker

O build de fonte atual requer Linux x86-64.

Use Docker Engine com Compose v2 em Linux. O primeiro build baixa releases verificadas por tamanho e SHA-256 e recompila FigCraft e GridCraft dos fontes Rust fixados, com correções de abrir/salvar no navegador e da entrada inicial de células, respectivamente. Os demais editores usam bundles upstream verificados com a preparação de marca documentada. Reserve tempo e disco adicionais para as dependências Rust; não é necessária GPU no servidor nem download de código no startup. Encoders e licenças originais são preservados; veja [os detalhes do build](docs/LICENSING.md#source-built-editors). O navegador desktop atualizado precisa de WebAssembly/WebGL; funções avançadas de áudio/vídeo dependem das capacidades do navegador.

Extraia o pacote, entre na pasta e execute:

```sh
./libertyctl up
./libertyctl token
```

Abra **http://localhost:8097**. O editor privado usa **http://localhost:8098** e os editores da demonstração usam **http://localhost:8099**, em origens separadas. O token inicial é aleatório e fica no volume; não existe senha padrão. Crie o administrador, cadastre seu autenticador TOTP e guarde os dez códigos de recuperação. Arquivos e aplicativos ficam bloqueados até confirmar MFA.

As três portas são publicadas em loopback por padrão. Configure as origens e portas no `.env` ao usar portas diferentes. O comando equivalente sem launcher é `docker compose up -d --build`.

## Domínio e HTTPS

Defina **três origens distintas** no `.env` antes de criar convites:

```sh
PUBLIC_ORIGIN=https://office.seu-dominio.com
EDITOR_ORIGIN=https://edit.office.seu-dominio.com
DEMO_EDITOR_ORIGIN=https://demo-edit.office.seu-dominio.com
```

Com Nginx Proxy Manager em Docker na rede existente `npm-bridge`:

```sh
docker compose -f compose.yaml -f deploy/compose.npm.yaml up -d --build
```

Crie três Proxy Hosts no NPM:

| Origem pública | Encaminhamento |
| --- | --- |
| `office.seu-dominio.com` | `http://liberty-office:8097` |
| `edit.office.seu-dominio.com` | `http://liberty-office:8097` |
| `demo-edit.office.seu-dominio.com` | `http://liberty-office:8097`, apenas GET/HEAD |

Todos devem ter TLS, Force SSL e preservar o cabeçalho `Host` original. O backend decide por esse cabeçalho quais recursos permitir. As origens dos editores não disponibilizam API de usuários, arquivos ou sessão. O portal não serve os bundles de edição. HTTPS é obrigatório fora de localhost, e subpastas como `/office` não são suportadas.

Para outra rede, configure `NPM_NETWORK`. Ao operar com overrides, preserve `COMPOSE_FILE=compose.yaml:deploy/compose.npm.yaml` em todos os comandos do launcher. Veja [operação](docs/OPERATIONS.pt-BR.md) para limites de proxy e armazenamento.

## Aplicativos incluídos


| Aplicativo | Uso | Release fixada |
| --- | --- | --- |
| WordCraft | Documentos e escrita | 0.7.0 |
| GridCraft | Planilhas e dados | 0.7.0 |
| DeckCraft | Apresentações | 0.7.0 |
| PdfCraft | Leitura e organização de PDFs | 0.8.0 |
| PhotoCraft | Edição de imagens | 0.9.0 |
| VectorCraft | Ilustração vetorial | 0.12.0 |
| LightCraft | Fotografia e RAW | 0.8.0 |
| FilmCraft | Edição de vídeo | 0.8.0 |
| EffectCraft | Motion design e efeitos | 0.10.0 |
| DesignCraft | Layout e publicação | 0.8.0 |
| FigCraft | Interfaces e protótipos | 0.6.0 |
| SoundCraft | Áudio | 0.7.0 |
| CADCraft | Desenho técnico | 0.7.0 |

Todos são os editores upstream reais. O Liberty não simula suas funções. A disponibilidade dos pacotes web foi verificada, inclusive a do FilmCraft, que ainda não era indicada na página geral do catálogo. Os aplicativos permanecem em evolução e não têm promessa de equivalência completa com Microsoft ou Adobe.

## Drive e edição

1. Envie um arquivo ao Drive ou abra um aplicativo para criar um projeto.
2. Clique no arquivo e escolha o aplicativo. Na barra do Liberty, **Carregar do Drive** oferece o conteúdo ao editor; dentro dele escolha **Arquivo → Abrir**.
3. Use **Arquivo → Salvar/Exportar** e confira **Salvo no Drive**. Uma exportação com o mesmo nome do arquivo próprio aberto cria uma revisão, com proteção ETag contra alterações concorrentes. Outro formato/nome cria outro arquivo.
4. Se o editor usar um mecanismo incompatível com o adaptador, baixe o original e use o seletor do aplicativo. **Enviar exportação ao Drive** oferece o caminho manual de volta.

O adaptador usa um canal privado entre origens. O editor recebe o arquivo escolhido e um protocolo limitado de exportação; cookies, CSRF e decisões sobre proprietário/ETag ficam no portal. Uma exportação de arquivo compartilhado cria uma cópia da pessoa que editou. Não há autosave universal ou colaboração centralizada.

Se a sessão expirar, preserve a exportação, entre na **mesma conta** em outra aba e use **Reconectar** para repetir o salvamento. Isso não recarrega o documento. Recarregar a página do editor pode perder alterações que ainda não foram exportadas. O estado local do aplicativo no navegador não equivale a arquivo persistido no Drive.

## Contas e armazenamento

Em **Administração**, crie contas e entregue o link de convite de uso único, válido por 48 horas. A pessoa escolhe senha e cadastra MFA. O painel permite reemitir convites, gerar recuperação de senha, alterar papel/cota e desativar/reativar contas. A recuperação de senha conserva o MFA existente; se o cadastro estava incompleto, reinicia o enrollment obrigatório. Não existe cadastro público nem opção de desligar MFA.

Em **Minha conta**, altere a senha e revogue sessões de outros dispositivos. Ações sensíveis exigem autenticação recente por senha e um novo TOTP. Desativação e mudança de papel revogam sessões, preservando os documentos.

O Drive oferece pastas, upload/download, renomeação, movimentação, pesquisa, compartilhamento interno de leitura, histórico privado, restauração de revisão como uma nova versão, lixeira e exclusão definitiva. Revisões antigas podem ser excluídas individualmente; a revisão atual fica protegida. Lixeira e todas as revisões ocupam cota até a exclusão.

| Configuração | Padrão | Uso |
| --- | --- | --- |
| `PUBLIC_ORIGIN` | `http://localhost:8097` | Origem exata do portal |
| `EDITOR_ORIGIN` | `http://localhost:8098` | Origem isolada dos editores |
| `DEMO_EDITOR_ORIGIN` | `http://localhost:8099` | Origem isolada da demonstração |
| `LIBERTY_PORT` / `EDITOR_PORT` / `DEMO_EDITOR_PORT` | 8097 / 8098 / 8099 | Portas publicadas no host |
| `LIBERTY_BIND` | `127.0.0.1` | Interface de publicação |
| `GLOBAL_QUOTA_BYTES` | 50 GiB | Blobs, revisões, lixeira e reservas de envio |
| `DEFAULT_QUOTA_BYTES` | 5 GiB | Cota de novas contas |
| `MAX_UPLOAD_BYTES` | 100 MiB | Máximo por upload/exportação |
| `LIBERTY_VOLUME_NAME` | `liberty_office_data` | Volume persistente |

Cotas são aplicadas no backend sob transação, inclusive em uploads simultâneos. O limite global não limita imagem, banco, logs ou backups. Alterar a cota padrão não altera contas existentes. Cota zero impede novos dados. Após mudar `.env`, use `docker compose up -d` para recriar o serviço sem remover o volume.

Para escolher disco ou diretório, use `deploy/compose.storage.yaml`. Uma instância e um worker por volume são suportados; SQLite WAL exige filesystem local. Não monte o mesmo banco em réplicas.

## Operação

```sh
./libertyctl status
./libertyctl verify
./libertyctl backup /caminho/privado/liberty-backup.tar.gz
./libertyctl recover nome-do-usuario
./libertyctl password-reset nome-do-usuario
```

Backup e recuperação operacional param o serviço e o reiniciam ao final. O backup contém banco, blobs, revisões e chave MFA. `recover` emite um código único para quem ainda conhece a senha e perdeu o autenticador; a pessoa deverá cadastrar novo MFA. `password-reset` emite um link de 30 minutos para redefinir a senha, inclusive do único administrador, conservando a exigência de MFA. Os dois mecanismos revogam sessões existentes. Guarde seus resultados em canal privado.

A chave `mfa.key` deve acompanhar o banco no backup. O startup recusa banco com chave ausente/incompatível. Restauração exige destino vazio, valida integridade SQLite, chaves, referências e hashes dos blobs, e revoga sessões antigas. Procedimento completo em [operações](docs/OPERATIONS.pt-BR.md).

## Verificação da entrega

```sh
python scripts/verify_release.py
python -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.txt
.venv/bin/python -m pytest -q
npm ci
npm test
```

Para homologar Docker e navegador em **dados descartáveis**, em um host Linux com Docker:

```sh
npx playwright install --with-deps chromium
scripts/docker_acceptance.sh
```

Esse gate constrói uma imagem própria de teste e um volume novo, verifica API/MFA, os 13 editores, reinício, integridade dos bundles, canal de exportação no Chromium e backup/restauração em outro volume. O seed sintético de teste é removido ao final. Não usa nem apaga o volume de produção. Há também um workflow de CI, sem publicação automática.

**Os testes de API, DOM, hashes, HTTP com os bundles reais e backup/restauração foram executados.** A imagem Docker foi construída no CT de implantação, os testes Python e Node passaram, e os fluxos de navegador descritos em [aceitação](docs/ACCEPTANCE.pt-BR.md) foram exercitados com dados fictícios. Esta candidata ainda requer homologação com seus documentos. Consulte também [operação](docs/OPERATIONS.pt-BR.md).

## Privacidade e licença

Os documentos ficam no armazenamento do seu servidor, legíveis pelo operador do host. **Não há E2EE equivalente ao CryptPad.** O isolamento por origem protege o portal dos scripts de edição; o navegador ainda mantém dados locais específicos dos aplicativos. Ao trocar a conta, o adaptador limpa Web Storage, IndexedDB, CacheStorage e OPFS antes de executar os motores e interrompe editores anteriores em outras abas. Salve no Drive antes de trocar de conta. Perfis separados de navegador continuam adequados para computadores compartilhados.

A imagem executa sem root, sem Docker socket, com raiz somente leitura, capabilities removidas, healthcheck e logs limitados. Senhas usam Argon2id; TOTP tem proteção contra replay e segredos criptografados por chave persistente. Leia [segurança](docs/SECURITY.pt-BR.md) para as fronteiras do modelo.

Código Liberty: **AGPL-3.0-or-later**, com fonte oferecido em `/source.zip`. O código principal dos editores declara **MIT OR Apache-2.0**, mas dependências, assets e marcas têm termos próprios. Consulte o [inventário e as condições de integração](docs/LICENSING.md), incluindo as substituições das marcas gráficas restritas, e a [verificação CodeMark](docs/INTEGRITY.md). As atribuições originais permanecem em `licenses/upstream/`. Não há afiliação com Microsoft, Adobe ou Artcraft.
