# Operação do Liberty Office

[English](OPERATIONS.md)

## Antes do primeiro acesso

Os comandos de operação usam inglês por padrão, independentemente do `LANG` do
host. Para português brasileiro, use `LIBERTY_CLI_LANGUAGE=pt-BR ./libertyctl token`
ou `LIBERTY_CLI_LANGUAGE=pt-BR python -m liberty.cli --help`. Qualquer outro valor
seleciona inglês. O `libertyctl` repassa essa escolha a cada comando Python pelo
`-e` do Compose, sem gravá-la no `.env` nem alterar o serviço em execução. No
Compose direto, use
`docker compose exec -T -e LIBERTY_CLI_LANGUAGE=pt-BR office python -m liberty.cli --help`.
Somente mensagens próprias são traduzidas. Tokens, URLs, caminhos, JSON de
status e stdout binário de backup permanecem iguais; diagnósticos do Docker,
argparse e outras dependências podem usar seu próprio idioma.

Configure `PUBLIC_ORIGIN`, `EDITOR_ORIGIN` e `DEMO_EDITOR_ORIGIN` com três origens exatas e distintas, sem barra final. Use HTTPS nas três; por exemplo `https://office.example.org`, `https://edit.office.example.org` e `https://demo-edit.office.example.org`. A origem controla Host, CSRF e os links de convite. O proxy deve manter Host e Origin; os cabeçalhos X-Forwarded-* não são tratados como prova de identidade. O backend não precisa saber o IP real do usuário para aplicar MFA. O throttle combina nome da conta e IP do proxy; muitos usuários em um único proxy podem compartilhar o limite de IP.

A porta publicada em loopback não pode ser acessada de outro computador. Um NPM em Docker deve compartilhar a rede, não usar `127.0.0.1` como se fosse o host. Use o override NPM. Exemplo com `npm-bridge`:

```sh
docker compose -f compose.yaml -f deploy/compose.npm.yaml up -d --build
docker compose -f compose.yaml -f deploy/compose.npm.yaml exec -T office python -m liberty.cli bootstrap-token
```

Crie três Proxy Hosts NPM: portal, editores privados e editores demo. Todos encaminham para `http://liberty-office:8097`, preservando Host, com TLS e Force SSL. A origem demo deve aceitar apenas GET/HEAD e corpo pequeno. As origens dos editores só permitem runtime e healthcheck; a API privada só responde na origem do portal. As portas publicadas locais são 8097, 8098 e 8099; na rede Docker todos os hosts usam a porta interna 8097. Ajuste o limite de corpo privado ao `MAX_UPLOAD_BYTES`. Configure também `proxy_read_timeout 360s;` e `proxy_send_timeout 360s;`. Envios muito lentos expiram após cinco minutos. WebAssembly/WebGL exigem suporte do navegador; alguns recursos de áudio e WebGPU exigem HTTPS e permissões do usuário.

Se quiser usar o launcher com overrides, defina `COMPOSE_FILE` com os mesmos arquivos, por exemplo em shell POSIX `COMPOSE_FILE=compose.yaml:deploy/compose.npm.yaml ./libertyctl status`. Em fish: `env COMPOSE_FILE=compose.yaml:deploy/compose.npm.yaml ./libertyctl status`. A mesma variável deve acompanhar backup e comandos de operação.

## Build de fonte e integridade dos editores

O build de fonte atual requer Linux x86-64. O Docker padrão recompila WordCraft,
FigCraft e GridCraft dos commits Rust fixados, com correções de ordem de texto
ao salvar/foco, abrir/salvar no navegador e entrada inicial de células,
respectivamente. Confere as saídas com `wordcraft-build.lock.json`,
`figcraft-build.lock.json` e `gridcraft-build.lock.json`. Os outros editores usam
bundles upstream verificados e a preparação de dados de marca documentada.
Rust, wasm-bindgen, fontes e arquivos de origem são fixados em
`scripts/build_wordcraft_web.sh`, `scripts/build_figcraft_web.sh` e `scripts/build_gridcraft_web.sh`; Cargo usa `--locked` e um job.
Reserve tempo, memória e disco adicionais para dependências e caches. O script
recusa iniciar ou terminar com menos de 5 GiB livres; esse piso não significa
que 5 GiB sejam suficientes para o build inteiro.
As etapas Docker serializam os builds de fonte, inclusive com BuildKit.
As receitas não impõem sozinhas limites de memória/CPU ao container; configure
esses limites no host de build. A implantação foi compilada em um builder
separado e limitado, não no container da aplicação em execução.

Não é necessária GPU no servidor; a homologação nativa do WordCraft usa pacotes
Vulkan por CPU fixados. A imagem de execução contém assets prontos,
não a toolchain Rust, e não baixa código de editores no startup. Uma imagem
local confiável com `/out` pode ser indicada no argumento de build
`WORDCRAFT_BUNDLE_IMAGE`, `FIGCRAFT_BUNDLE_IMAGE` ou `GRIDCRAFT_BUNDLE_IMAGE` para reusar o build testado
do editor correspondente. Cada imagem precisa de um shell para a etapa
condicional de build. Hashes dos arquivos
compilados e dos patches/receitas atuais continuam obrigatórios; um bundle
arbitrário ou antigo é recusado. Preserve licenças e registros de modificação.

## Escolher onde armazenar os dados

O volume padrão chama-se `liberty_office_data`. Ele inclui `liberty.db`, blobs privados, chave `mfa.key`, arquivos temporários e token inicial até o bootstrap. Não coloque esse diretório em um webroot nem apague a chave: sem ela, os segredos TOTP existentes deixam de ser decifráveis.

Para bind mount, prepare um diretório vazio pertencente a UID/GID 10001. Exemplo no host, ajustando o caminho de forma consciente:

```sh
sudo install -d -m 700 -o 10001 -g 10001 /srv/liberty-office-data
```

Defina `LIBERTY_DATA_PATH=/srv/liberty-office-data` no `.env` e execute:

```sh
docker compose -f compose.yaml -f deploy/compose.storage.yaml up -d --build
```

Os overrides podem ser combinados. Eles não migram dados automaticamente. Para migrar de volume para bind mount ou outro disco, faça backup, restaure em destino vazio e só então passe o serviço para o novo destino. Docker data-root e a imagem não são controlados pelas cotas do Drive. LightCraft é o maior pacote WASM; dimensione disco para a imagem, cache de build e dados adicionais.

## Backup consistente

O comando `./libertyctl backup /caminho/arquivo.tar.gz` usa Compose para parar o serviço e reiniciá-lo ao final. O diretório de saída deve existir e estar fora do volume para manter uma cópia independente. Se usa overrides, preserve `COMPOSE_FILE`. O launcher não remove volumes.

Para realizar manualmente:

```sh
docker compose stop office
docker compose run --rm --no-deps -T office python -m liberty.cli backup --stdout > liberty-office-backup.tar.gz
docker compose up -d office
```

O CLI recusa backup se o processo que serve o volume estiver ativo. O snapshot inclui todos os blobs referenciados e suas revisões, banco e chave MFA. `BACKUP.json` registra tamanhos e SHA-256. O formato não é criptografado; controle as permissões e criptografe o arquivo com sua ferramenta usual antes de enviá-lo a terceiros ou backup remoto.

## Restaurar em novo volume

Mantenha o volume original. Para testar restauração em outro volume, pare a instância original para evitar conflito de portas e nomes, coloque o backup no diretório atual como `liberty-office-backup.tar.gz` e execute:

```sh
docker compose stop office
docker volume create liberty_office_restored
docker run --rm -i --user 10001:10001 --mount source=liberty_office_restored,target=/data liberty-office:0.2.0-rc.1 python -m liberty.cli restore - /data < liberty-office-backup.tar.gz
```

O volume novo deve herdar a propriedade de `/data` da imagem. Se a plataforma criar o volume com propriedade root e o comando retornar permissão negada, inicialize apenas esse volume novo com `docker run --rm --user 0:0 --mount source=liberty_office_restored,target=/data liberty-office:0.2.0-rc.1 chown 10001:10001 /data` e repita. Não execute chown recursivo em um volume desconhecido.

O exemplo transfere o backup privado por stdin: o arquivo não precisa ficar legível para UID 10001 no host. A restauração usa espaço temporário no volume para o arquivo compactado e a extração; reserve essa margem. O CLI aceita apenas arquivos esperados, valida os hashes e recusa destinos não vazios. Segredos MFA e hashes de senhas são preservados. As sessões e reservas antigas são apagadas na restauração. Em seguida, altere `LIBERTY_VOLUME_NAME=liberty_office_restored` no `.env` e recrie o serviço. Confira login com MFA e download de documentos antes de remover qualquer cópia antiga.

Um backup não testado não é garantia de restauração. O teste automatizado desta entrega exercita backup offline, validação e restauração com MFA e um arquivo real. Sua validação no Docker de destino continua necessária.

## Manutenção e limites

### Runtime público durante a manutenção das contas

`liberty.public_app:create_public_app` é uma factory ASGI separada, somente de
leitura. Use as mesmas três origens e os caminhos verificados de aplicativos,
gerações públicas e oferta de fontes, montados somente para leitura. Não monte
o volume privado nem forneça credenciais de contas. Ela não cria banco, chave
MFA, sessão, token de bootstrap ou bloqueio do volume. A resposta de saúde inclui
`mode: public-only` e a geração pública validada; não comprova a saúde das contas.

A página de manutenção tem inglês como padrão, português brasileiro como opção
e link para a demo funcional. Somente rotas públicas explícitas GET/HEAD estão
disponíveis. Contas e salvamentos no portal retornam 503, sem reenvio automático
nem prazo prometido; as rotas de editores privados ficam indisponíveis. GET/HEAD
de `/public-assets/` verificados e imutáveis continua nas três origens, incluindo
as gerações atual e anterior; isso não concede acesso ao runtime privado. Os
documentos da demo permanecem no navegador: baixe uma cópia e use Concluir e
limpar. O runtime público não enfileira salvamentos nem guarda backups deles.

Iniciar essa factory não realiza uma troca segura por si só. Valide o roteamento,
o encerramento dos workers antigos do proxy, a saída normal do backend e a
conciliação dos dados autoritativos antes de trocar o escritor em produção. Não
use o wrapper comum de backup/recuperação, que para primeiro o serviço, como
controlador de manutenção blue/green.

### Limites operacionais

- Para atualizar: backup, revisar `upstream.lock.json`, obter o hash oficial da release desejada, reconstruir e validar documentos de exemplo. Não use `latest` silenciosamente para editores.
- Um worker e uma instância por volume. O bloqueio de arquivo impede startup concorrente. SQLite WAL reside em filesystem local; não é indicado manter esse banco em NFS ou entre hosts.
- No startup após um processo encerrado, reservas de uploads e temporários interrompidos são liberados. Blobs órfãos de uma queda entre rename e commit não são removidos automaticamente; não apague blobs manualmente durante o serviço. Um backup usa apenas blobs referenciados e sua restauração em volume novo elimina órfãos.
- Revisões não têm expiração automática. O proprietário pode baixar, restaurar como nova revisão e excluir revisões antigas no painel. A revisão atual não pode ser excluída isoladamente. Compartilhamento não libera histórico ao destinatário.
- O painel reemite convite de contas ainda não ativadas e emite recuperação de senha para contas ativadas, inclusive com MFA incompleto. Tokens anteriores deixam de funcionar. Não altere o banco diretamente durante operação.
- MFA web usa TOTP e códigos de recuperação. Passkeys/WebAuthn, OIDC/LDAP, grupos, S3, cotas por pasta e E2EE não estão implementados.

## Recuperação de contas

`./libertyctl recover usuario` para o serviço, obtém bloqueio exclusivo, revoga sessões e códigos anteriores e imprime um código de recuperação único. O usuário entra com a senha existente e esse código, cadastra outro autenticador e só então acessa o Drive.

`./libertyctl password-reset usuario` também opera offline e imprime um link de uso único de 30 minutos. Serve inclusive quando o único administrador esqueceu a senha. Não redefine nem revela um MFA já confirmado. Se a conta ainda estava em enrollment, o consumo do link cria um novo segredo e exige concluir o MFA. Se senha e autenticador foram perdidos, use os dois comandos e os respectivos mecanismos; o cadastro MFA continua obrigatório.

Os launchers reiniciam o serviço ao final, inclusive se o CLI falhar. Esses comandos têm autoridade de operador do host. Não encaminhe os resultados para logs públicos. `status` abre o banco em modo somente leitura e nunca cria/migra um volume; `doctor --deep` verifica integridade, não certifica produção.

## Atualizar de 0.1.0-preview

1. Faça backup offline com a versão antiga e preserve a imagem/pacote anterior.
2. Extraia 0.2.0-rc.1 em outro diretório. Preserve o `.env` e o nome do volume; configure `EDITOR_ORIGIN`, `EDITOR_PORT=8098` e o segundo host HTTPS antes da troca. Convites passam a usar a origem exata do portal.
3. Pare a instância antiga. Construa e inicie a nova, mantendo apenas um worker e uma instância por volume.
4. O banco migra da versão 1 para 2 por criação idempotente de tabelas. Usuários, TOTP, blobs, versões e compartilhamentos são preservados. Reabra o portal e os editores para obter a nova interface e as novas capacidades de sessão.
5. Execute `./libertyctl verify`, valide MFA, download de documento antigo, exportação nova, cotas e o segundo host. Homologue com dados de teste antes de aplicar a uma implantação com documentos reais.

Não faça downgrade apontando a imagem antiga para um banco migrado. Para rollback, pare a candidata e restaure o backup anterior em outro volume, usando a versão anterior. A versão atual recusa bancos com versão de esquema mais recente do que ela suporta.

## Diagnóstico e aceitação

`./libertyctl status` mostra contagens, versão e ocupação referenciada. `./libertyctl verify` valida Compose e hashes instalados, SQLite, MFA e disco disponível. Sua saída distingue integridade técnica de homologação de produção.

A imagem tem base e dependências fixadas; não altere hashes para contornar um download inválido. O primeiro build precisa acessar GitHub e PyPI. Depois de construir, a aplicação serve seus próprios assets. Para atualizar releases Artcraft, revise as novas licenças e artefatos, fixe versão/URL/tamanho/SHA-256 e repita a homologação.

O script `scripts/docker_acceptance.sh` cria projeto, imagem e volumes próprios com nomes `liberty-acceptance-*`; o Compose de produção não é selecionado. Ele exige npm dependencies e Chromium instalados no host e deixa relatórios sem o seed em `acceptance-results/` e `playwright-report/`. Consulte `docs/ACCEPTANCE.md` para o que o gate comprova e para a verificação de formatos reais.
