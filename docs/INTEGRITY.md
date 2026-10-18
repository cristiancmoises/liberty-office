# Source integrity / Integridade do fonte

## English

This project includes SecOps CodeMark 0.4.1 metadata in `.codemark/`.
The selected published tree is hashed with SHA-256 and SHA-512 and its reference
is signed with both ML-DSA-87 and Ed25519. The original source and third-party
license texts are not marked or rewritten. Private keys stay outside the project.

Verify a clean export of the intended signed Git commit, before installing
dependencies or creating local configuration. The snapshot covers regular
published files and their POSIX modes, not `.git` or `.codemark` metadata.
An ordinary working directory containing `.env`, caches or dependencies is
not that clean export. Do not refresh the snapshot to make a changed tree pass.

1. Obtain SecOps CodeMark 0.4.1 from its [official project](https://codemark.securityops.co/en/downloads/) and independently verify the verifier.
2. Independently confirm the maintainer's OpenPGP fingerprint:
   `0CFA43B9AA9642EAAF2BE983C4C661C9ECFB46E8`.
3. Check `git verify-commit COMMIT`, export that exact revision using
   `git -c tar.umask=0022 archive COMMIT | tar -x -C /new/empty/directory`, and authenticate
   `.codemark/trust.json` with its detached `trust.json.asc` signature:
   `gpg --verify .codemark/trust.json.asc .codemark/trust.json`.
   Require the expected fingerprint, not merely any valid signature.
4. Retain both full public fingerprints and the checkpoint from that authenticated
   record outside the tree, then run:

```sh
python3 /trusted/codemark.pyz audit /new/empty/directory \
  --pq-fingerprint YOUR_TRUSTED_PQ_FINGERPRINT \
  --classical-fingerprint YOUR_TRUSTED_CLASSICAL_FINGERPRINT \
  --checkpoint YOUR_TRUSTED_CHECKPOINT --json
```

Use Python 3.10+ and OpenSSL 3.5+ with ML-DSA-87 and Ed25519 support. Check the exit
status, current-tree integrity and authentication results. Keeping the latest
checkpoint independently detects replacement by an older signed history.
Git-forge signature badges are separate from local cryptographic verification.

The explicit archive umask preserves canonical 0644/0755 source modes. Git's
default tar export may otherwise add group-write permission, which the mode
integrity check correctly rejects. Use the same explicit umask when exporting
the build context; do not relax mode verification to accept that difference.

CodeMark detects differences against an authenticated reference. It is not a
malware scan, a vulnerability guarantee, proof of legal ownership, a trusted
timestamp, or protection against a compromised signing key. Checksums alone
cannot authenticate a replacement manifest. See the
[CodeMark security guidance](https://codemark.securityops.co/en/docs/security/).

## Português brasileiro

A pasta `.codemark/` contém o inventário SHA-256/SHA-512 e a atestação híbrida
ML-DSA-87 + Ed25519 do fonte publicado. As chaves privadas não são distribuídas.
Licenças e arquivos de terceiros permanecem preservados.

Verifique uma exportação limpa do commit assinado antes de instalar dependências.
Confirme o fingerprint OpenPGP acima por um canal independente, verifique a
assinatura de `trust.json` e use seus dois fingerprints públicos e checkpoint no
comando de auditoria. Guarde esses valores fora da árvore. A cobertura inclui
bytes e modos POSIX dos arquivos publicados; exclui os metadados `.git` e
`.codemark`. Não gere outro snapshot para esconder diferenças.

Ao exportar fonte ou contexto de build, use `git -c tar.umask=0022 archive`.
Esse parâmetro preserva os modos 0644/0755; a exportação tar padrão do Git pode
adicionar escrita para grupo. Não afrouxe a verificação para aceitar essa diferença.

O resultado comprova correspondência com a referência autenticada, não ausência
de vulnerabilidades, autoria legal ou data confiável. A retenção independente
do checkpoint é necessária para detectar retorno a uma versão antiga assinada.
