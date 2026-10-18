# Segurança e privacidade

[English](SECURITY.md)

## Identidade

Toda conta precisa de senha Argon2id e TOTP confirmado. Não existe senha padrão, bypass web ou opção de desativar MFA. O token aleatório de bootstrap só funciona em banco vazio. Convites de 48 horas e links de redefinição de 30 minutos são aleatórios, de uso único e guardados como hashes.

Cadastro público gratuito, sem convite, fica disponível quando o operador
habilita `PUBLIC_SIGNUP_ENABLED` após confirmar MFA da administração. Cria
usuário comum com cota separada de 100.000.000 bytes; campos como papel, cota ou
outros desconhecidos são rejeitados. Não permite assumir o bootstrap
administrativo. O padrão é desabilitado para instalações próprias existentes.

O cadastro tem limites persistentes de tentativas por origem (5 por hora),
sucessos globais (20 por hora) e capacidade de contas públicas (400). Tentativas
contam mesmo quando a criação falha; contador de sucesso, usuário e sessão são
gravados atomicamente. Somente `TRUSTED_PROXY_CIDRS` explicitamente configurados
podem fornecer uma cadeia de encaminhamento: usa-se o par não confiável mais à
direita; cabeçalhos inválidos voltam ao par direto. Configuração incorreta pode
agrupar usuários no mesmo limite; não resolva isso confiando em todos os proxies.

Cada transação de cadastro pode limpar no máximo 100 cadastros públicos
incompletos após as 24 horas configuradas. A limpeza exclui contas estabelecidas,
desativadas ou protegidas, convites, arquivos, versões, reservas e
compartilhamentos recebidos. A primeira confirmação MFA marca a conta como
estabelecida permanentemente; recuperação ou reset de MFA posteriores não a
tornam descartável. Contas antigas ficam fora dessa limpeza. Não é uma política
de retenção dos arquivos das contas. Antes de permitir um escritor antigo, sem
essa instrumentação, no banco, marque todos os registros públicos como
`cleanup_protected=1`; nunca execute escritores antigos e novos simultaneamente.

Senha tem mínimo de 14 caracteres e limite de 256. No máximo duas operações Argon simultâneas limitam memória por processo. O throttle persistente verifica o IP antes de criar chaves por nome de conta. A API limita JSON a 16 KiB antes do parser e uploads ao limite configurado, com tempo máximo de recebimento. Respostas de validação não repetem os valores recebidos.

Sessões opacas ficam como hashes no banco. Cookies são HttpOnly, SameSite Strict e Secure quando HTTPS; rotacionam entre senha, MFA e acesso completo. Sessões pendentes não acessam documentos/editores. TOTP de 30 segundos aceita janela de um intervalo e rejeita replay sob transação. A chave Fernet persistente protege os segredos TOTP contra vazamento isolado do banco, não contra uma cópia integral do volume.

Dez códigos de recuperação aleatórios ficam como hashes e são consumidos atomicamente. Recuperação exige a senha e força cadastrar outro MFA. Reset de senha de conta estabelecida conserva o autenticador. Contas com enrollment incompleto recebem um segredo novo. Desativação, alteração de papel e recuperação revogam sessões; a confirmação inicial MFA revoga os outros desafios. Mutações revalidam sessão, papel e autenticação recente dentro da transação de escrita.

## Fronteira entre portal e editores

`PUBLIC_ORIGIN`, `EDITOR_ORIGIN` e `DEMO_EDITOR_ORIGIN` devem ser distintas. O servidor verifica Host completo, incluindo porta. Só a origem do portal permite API, interface e arquivos. A origem privada de edição permite `/runtime/TICKET/...`; a origem de demo serve assets anônimos, sem acesso às APIs de contas ou Drive. O middleware não concede CORS entre elas.

Cada ticket fica vinculado a uma sessão completa, um aplicativo e sua expiração. Revogação de sessão invalida o ticket. O HTML servido adia os módulos até limpar o estado local e estabelecer o adaptador. A preparação dos assets e os builds de fonte de WordCraft, FigCraft e GridCraft estão descritos em [licenciamento](LICENSING.md). A origem dos editores não recebe senha ou CSRF no HTML.

Exportações da demo usam um protocolo separado e limitado para download local.
O portal aceita bytes somente do frame ativo e da origem exata da demo, valida
formato e tamanho da mensagem e cria a URL de download. Não aceita URL de API
nem acessa o Drive. Isso evita incompatibilidades de download Blob em iframe
sem afrouxar sandbox ou preferências de privacidade. A confirmação indica
início do download, não que o usuário já salvou o arquivo em disco.

Selecionar arquivo na demo não é upload ao servidor. A política compartilhada
verifica metadados antes de ler bytes, reserva o consumo cumulativo do projeto
e valida texto e estrutura decodificados antes de entregar o File ao editor.
Falha na validação de conteúdo consome o limite de leitura; metadados rejeitados
não consomem. Formatos ricos da área de transferência e atalhos nativos de
texto SVG/HTML/RTF/data-URI são bloqueados. Texto puro colado tem limites
estruturais próprios. Não é um sanitizador genérico de qualquer documento.

O controlador limpa dados antigos antes de admitir outro motor. Uma segunda
trava impede que um controlador novo limpe um editor atual ainda vivo. Concluir
suspende exportações, descarrega o motor, aguarda limpeza de WebStorage,
IndexedDB, CacheStorage e OPFS, revoga URLs de download e só então libera a
sessão. Limpeza bloqueada ou com falha não é anunciada como concluída. A demo do
LightCraft usa seu backend nativo em memória para evitar miniaturas persistidas;
bibliotecas privadas mantêm o backend normal. O Service Worker antigo do Effect
precisa encerrar antes da remoção de caches. Abas antigas, anteriores a essas
travas, devem ser fechadas antes de atualizar. Fechamento inesperado do navegador
não garante exclusão imediata; a próxima admissão tenta limpar novamente. É
processamento local temporário, não armazenamento anônimo no servidor nem
garantia de apagamento seguro.

O MessageChannel exige janela de origem, origem exata e nonce aleatório. As mensagens permitem oferecer conteúdo escolhido e exportar bytes de tamanho limitado; não permitem escolher uma URL de API ou o proprietário de um arquivo. Cookies, CSRF, ETag e decisão de revisão/cópia pertencem ao portal. Reconexão do salvamento exige a mesma identidade do editor aberto.

O iframe tem sandbox e a CSP limita conexões a recursos locais. Os editores reais precisam de JavaScript, WebAssembly, estilos inline, Blobs e recursos de mídia. Eles continuam sendo código upstream confiado dentro da origem de edição; isso não é um sandbox individual para código arbitrário ou plugins não confiáveis. A CSP não equivale a um firewall de saída do host/navegador.

Na troca de conta, o adaptador limpa Web Storage, IndexedDB, CacheStorage e OPFS. Locks serializam a limpeza nos navegadores que os suportam. Uma falha de limpeza impede o carregamento do motor. BroadcastChannel encerra documentos anteriores em outras abas. Isso evita persistência acidental entre contas; o controle por origem do navegador e as permissões do sistema continuam sendo fronteiras relevantes. Use perfis distintos em computadores compartilhados.

## Dados e operação

Cada acesso ao Drive verifica proprietário/compartilhamento. Compartilhamentos são internos e de leitura; destinatários acessam a versão atual, não o histórico privado do proprietário. Exportações viram cópias próprias. Downloads são attachment/octet-stream/nosniff. Nomes de arquivo não determinam caminhos de blobs, que usam UUID.

Revisões imutáveis e ETag/If-Match protegem atualizações e restauração contra concorrência. Quotas incluem revisões, lixeira e reservas de upload sob transação. Excluir uma revisão atual isolada é proibido. O log de auditoria tem tamanho limitado e não registra conteúdo de documentos, senhas ou tokens.

O armazenamento de contas públicas é persistente e separado da demo local do
navegador. A cota pública padrão é exatamente 100 MB (100.000.000 bytes), não
100 MiB. A interface mostra uso, reservas e espaço disponível; downloads seguem
disponíveis quando novos envios estão bloqueados. Controles administrativos
de cota usam GiB explicitamente. Alterar padrões não redimensiona contas existentes.

Há um bloqueio exclusivo por volume antes de abrir/migrar o banco. Backup, restauração e recuperação operacional cooperam com esse bloqueio. Status e diagnóstico não migram o banco. Restauração valida hashes, referências, integridade SQLite, chaves MFA e destino vazio; apaga sessões e reservas restauradas. A imagem roda sem root/capabilities, sem socket Docker, com raiz read-only e logs limitados.

O Docker socket, a chave MFA e o volume dão controle sobre os dados. Restrinja-os aos operadores. Backups não são criptografados pelo formato do Liberty; proteja o arquivo usando sua infraestrutura habitual e teste a restauração em volume separado.

## Limites do modelo

**Não há E2EE.** O operador do host pode ler documentos. Não há antivírus, WebAuthn/passkeys, OIDC/LDAP, S3, isolamento de código arbitrário por tenant nem certificação ou auditoria externa. MFA e cotas não impedem quem recebeu um arquivo de copiá-lo. A suíte não promete fidelidade de todos os formatos Office/Adobe nem autosave universal.

Antes de exposição pública, execute a aceitação Docker/browser e a verificação de formatos no host e proxy escolhidos. O relatório da release distingue testes executados de testes pendentes. Reporte falhas de forma privada ao mantenedor da sua implantação, preservando documentos e segredos.
