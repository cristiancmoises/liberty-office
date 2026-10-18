"""Translate application-owned response messages, never document/account data."""


def language(request):
    value = (
        request.headers.get("accept-language", "en")
        .split(",")[0]
        .split(";")[0]
        .strip()
        .lower()
    )
    return "pt-BR" if value == "pt-br" else "en"


def translate(message, request):
    if not isinstance(message, str):
        return message
    if language(request) == "pt-BR":
        return PT.get(message, message)
    prefix = "Value error, "
    if message.startswith(prefix):
        return prefix + EN.get(message[len(prefix) :], message[len(prefix) :])
    return EN.get(message, message)


PT = {
    "Public registration is not available.": "Cadastro público indisponível.",
    "The operator must finish initial setup before registration opens.": "O operador precisa concluir a configuração inicial antes de abrir os cadastros.",
    "That username is already registered.": "Esse nome de usuário já está cadastrado.",
    "Public account capacity is temporarily full.": "A capacidade de contas públicas está temporariamente esgotada.",
    "Registration is busy. Please try again later.": "O cadastro está ocupado. Tente novamente mais tarde.",
}


EN = {
    "A oferta de código fonte está incluída na imagem Docker e no pacote de distribuição.": "The source offer is included in the Docker image and distribution package.",
    "Escrita, revisão e documentos.": "Writing, reviewing, and documents.",
    "Dados, fórmulas e planilhas.": "Data, formulas, and spreadsheets.",
    "Ideias que ganham a tela.": "Ideas brought to the screen.",
    "Composição e edição de imagens.": "Image composition and editing.",
    "Ilustração e desenho vetorial.": "Illustration and vector drawing.",
    "Monte histórias em movimento.": "Build stories in motion.",
    "Fotografia, biblioteca e RAW.": "Photography, libraries, and RAW.",
    "Leia, organize e transforme PDFs.": "Read, organize, and transform PDFs.",
    "Motion design e efeitos visuais.": "Motion design and visual effects.",
    "Layout, páginas e publicação.": "Layouts, pages, and publishing.",
    "Interfaces e protótipos.": "Interfaces and prototypes.",
    "Grave, edite e mixe áudio.": "Record, edit, and mix audio.",
    "Desenho técnico e projetos CAD.": "Technical drawing and CAD projects.",
    "Documentos": "Documents",
    "Planilhas": "Spreadsheets",
    "Apresentações": "Presentations",
    "Criação": "Creative",
    "Fotografia": "Photography",
    "Vídeo": "Video",
    "Áudio": "Audio",
    "Engenharia": "Engineering",
    "A configuração MFA já foi concluída.": "MFA setup is already complete.",
    "A configuração inicial já foi concluída.": "Initial setup is already complete.",
    "A cota foi alterada durante a restauração.": "The quota changed during restoration.",
    "A cota foi alterada durante o envio.": "The quota changed during upload.",
    "A revisão atual não pode ser excluída isoladamente.": "The current revision cannot be deleted separately.",
    "A revisão foi removida durante a restauração.": "The revision was removed during restoration.",
    "Abra a demonstração na origem isolada.": "Open the demo on its isolated origin.",
    "Abra o aplicativo pelo portal. Editores agora usam uma origem isolada.": "Open the app from the portal. Editors use an isolated origin.",
    "Abra os editores na origem isolada.": "Open editors on their isolated origin.",
    "Acesso administrativo necessário.": "Administrator access required.",
    "Adaptador não encontrado.": "Adapter not found.",
    "Aguarde a conclusão dos envios em andamento.": "Wait for current uploads to finish.",
    "Aplicativo não encontrado.": "App not found.",
    "Arquivo do aplicativo não encontrado.": "App file not found.",
    "Arquivo excede o limite por envio.": "File exceeds the upload limit.",
    "Arquivo indisponível. Verifique a restauração do volume.": "File unavailable. Check the volume restoration.",
    "Arquivo não encontrado.": "File not found.",
    "Arquivo ou pasta não encontrado.": "File or folder not found.",
    "Compartilhe arquivos individuais nesta versão.": "Share individual files in this version.",
    "Configuração MFA indisponível nesta sessão.": "MFA setup is unavailable in this session.",
    "Confirme o MFA antes desta operação.": "Verify MFA before this operation.",
    "Confirme o MFA para continuar.": "Verify MFA to continue.",
    "Confirme sua senha e um novo código MFA para esta ação.": "Verify your password and a fresh MFA code for this action.",
    "Conta ativa não encontrada.": "Active account not found.",
    "Conta ativada não encontrada. Reemita o convite para contas novas.": "Activated account not found. Reissue the invitation for new accounts.",
    "Conta indisponível.": "Account unavailable.",
    "Conta não encontrada.": "Account not found.",
    "Content-Length inválido.": "Invalid Content-Length.",
    "Content-Length é obrigatório para aplicar cotas antes do envio.": "Content-Length is required to enforce quotas before upload.",
    "Convite inválido ou expirado.": "Invalid or expired invitation.",
    "Corpo JSON excede 16 KiB.": "JSON body exceeds 16 KiB.",
    "Código inválido, expirado ou já utilizado.": "Invalid, expired, or already used code.",
    "Destinatário não encontrado.": "Recipient not found.",
    "Entre na sua conta.": "Sign in to your account.",
    "Envie o item para a lixeira antes de excluir definitivamente.": "Move the item to trash before permanently deleting it.",
    "Envio incompleto: Content-Length não corresponde ao corpo.": "Incomplete upload: Content-Length does not match the body.",
    "Espaço insuficiente na cota. Versões e lixeira também ocupam espaço.": "Insufficient quota. Versions and trash also count toward storage.",
    "Esta conta já foi ativada. Use recuperação de senha.": "This account is already activated. Use password recovery.",
    "Este item não é um arquivo.": "This item is not a file.",
    "Feche um editor antes de abrir outro.": "Close an editor before opening another.",
    "Host não autorizado.": "Host not allowed.",
    "Há um item com o mesmo nome no destino. Renomeie-o antes de restaurar.": "An item with this name exists at the destination. Rename it before restoring.",
    "If-Match é obrigatório para preservar revisões concorrentes.": "If-Match is required to preserve concurrent revisions.",
    "If-Match é obrigatório para restaurar conteúdo.": "If-Match is required to restore content.",
    "Já existe um item com esse nome nesta pasta.": "An item with this name already exists in this folder.",
    "Já existe um item com esse nome no destino.": "An item with this name already exists at the destination.",
    "Link de recuperação inválido ou expirado.": "Invalid or expired recovery link.",
    "MFA já confirmado.": "MFA already verified.",
    "Muitas tentativas. Aguarde alguns minutos.": "Too many attempts. Wait a few minutes.",
    "Nome de usuário já existe.": "Username already exists.",
    "Nome inválido. Use até 180 caracteres, sem caminhos ou controles.": "Invalid name. Use up to 180 characters without paths or control characters.",
    "O arquivo mudou. Abra a versão atual antes de salvar.": "The file changed. Open the current version before saving.",
    "O arquivo mudou. Atualize antes de restaurar.": "The file changed. Refresh before restoring.",
    "O corpo excede o Content-Length declarado.": "The body exceeds the declared Content-Length.",
    "O destino precisa ser uma pasta.": "The destination must be a folder.",
    "O disco do servidor não tem espaço livre suficiente.": "The server disk does not have enough free space.",
    "O envio excedeu cinco minutos. Tente novamente.": "The upload exceeded five minutes. Try again.",
    "O histórico é privado do proprietário.": "Version history is private to the owner.",
    "Origem não autorizada.": "Origin not allowed.",
    "Outra revisão foi salva durante a restauração.": "Another revision was saved during restoration.",
    "Outra revisão foi salva durante o envio.": "Another revision was saved during upload.",
    "Pacote web não instalado.": "Web package not installed.",
    "Recurso não encontrado.": "Resource not found.",
    "Reemita o convite para esta conta ainda não ativada.": "Reissue the invitation for this inactive account.",
    "Restaure primeiro a pasta que contém este item.": "Restore the containing folder first.",
    "Revisão não encontrada.": "Revision not found.",
    "Senha atual inválida.": "Invalid current password.",
    "Senha ou código inválidos.": "Invalid password or code.",
    "Senha ou código inválidos. Use um código novo.": "Invalid password or code. Use a fresh code.",
    "Sessão do editor inválida ou expirada.": "Invalid or expired editor session.",
    "Sessão expirada durante o envio.": "Session expired during upload.",
    "Sessão expirada.": "Session expired.",
    "Sessão expirada. Entre novamente sem fechar o editor.": "Session expired. Sign in again without closing the editor.",
    "Sessão não encontrada.": "Session not found.",
    "Sessão revogada ou expirada.": "Session revoked or expired.",
    "Tempo de envio excedido.": "Upload timed out.",
    "Token CSRF ausente ou inválido.": "Missing or invalid CSRF token.",
    "Token inicial inválido.": "Invalid setup token.",
    "Uma pasta não pode ser movida para dentro dela mesma.": "A folder cannot be moved inside itself.",
    "Use letras, números, ponto, hífen ou sublinhado.": "Use letters, numbers, dots, hyphens, or underscores.",
    "Usuário ou senha inválidos.": "Invalid username or password.",
    "Visualização inválida.": "Invalid view.",
    "Você não pode desativar ou remover seu próprio papel de administrador.": "You cannot disable your account or remove your own administrator role.",
}
