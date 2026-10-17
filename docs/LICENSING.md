# Editor licensing and integration

[Português brasileiro](#português-brasileiro)

Liberty Office's own portal and integration code are **AGPL-3.0-or-later**.
That does not relicense the independent editors, their dependencies, fonts,
models, assets or trademarks. The pinned release inventory is
[`upstream.lock.json`](../upstream.lock.json); original notices are preserved in
[`licenses/upstream/`](../licenses/upstream/).

The [source and notice inventory](../licenses/upstream/SOURCES.json) records
exact commits and SHA-256 hashes for the 13 editor sources, four craft-fonts
revisions and selected Cargo.lock-verified dependency sources, including the
MPL-covered acadrust and Symphonia crates. Their complete source download URLs
are included there. The portal source offer includes this inventory and the
preserved notices, not those complete third-party source archives.

## Pinned editor inventory

Each editor's primary code declares **MIT OR Apache-2.0**, at the recipient's
option. This permits modification, integration and redistribution, subject to
the chosen license and separate third-party terms. It is not a blanket license
for every bundled asset or dependency.

| Editor | Version | Original notices | Source |
| --- | --- | --- | --- |
| WordCraft | v0.7.0 | [Notices](../licenses/upstream/wordcraft/NOTICE) | [Upstream](https://github.com/storytold/wordcraft/tree/v0.7.0) |
| GridCraft | v0.7.0 | [Notices](../licenses/upstream/gridcraft/NOTICE) | [Upstream](https://github.com/storytold/gridcraft/tree/v0.7.0) |
| DeckCraft | v0.7.0 | [Notices](../licenses/upstream/deckcraft/NOTICE) | [Upstream](https://github.com/storytold/deckcraft/tree/v0.7.0) |
| PhotoCraft | v0.9.0 | [Notices](../licenses/upstream/photocraft/NOTICE) | [Upstream](https://github.com/storytold/photocraft/tree/v0.9.0) |
| VectorCraft | v0.12.0 | [Notices](../licenses/upstream/vectorcraft/NOTICE) | [Upstream](https://github.com/storytold/vectorcraft/tree/v0.12.0) |
| FilmCraft | v0.8.0 | [Notices](../licenses/upstream/filmcraft/NOTICE) | [Upstream](https://github.com/storytold/filmcraft/tree/v0.8.0) |
| EffectCraft | v0.10.0 | [Notices](../licenses/upstream/effectcraft/NOTICE) | [Upstream](https://github.com/storytold/effectcraft/tree/v0.10.0) |
| DesignCraft | v0.8.0 | [Notices](../licenses/upstream/designcraft/NOTICE) | [Upstream](https://github.com/storytold/designcraft/tree/v0.8.0) |
| FigCraft | v0.6.0 | [Notices](../licenses/upstream/figcraft/NOTICE) | [Upstream](https://github.com/storytold/figcraft/tree/v0.6.0) |
| SoundCraft | v0.7.0 | [Notices](../licenses/upstream/soundcraft/NOTICE) | [Upstream](https://github.com/storytold/soundcraft/tree/v0.7.0) |
| CADCraft | v0.7.0 | [Notices](../licenses/upstream/cadcraft/NOTICE) | [Upstream](https://github.com/storytold/cadcraft/tree/v0.7.0) |
| PdfCraft | v0.8.0 | [Notices](../licenses/upstream/pdfcraft/NOTICE) | [Upstream](https://github.com/storytold/pdfcraft/tree/v0.8.0) |
| LightCraft | v0.8.0 | [Notices](../licenses/upstream/lightcraft/NOTICE) | [Upstream](https://github.com/storytold/lightcraft/tree/v0.8.0) |

## Conditions to preserve

- **MIT:** retain the copyright and permission notice in copies or substantial
  portions. [Authoritative license](https://opensource.org/license/mit).
- **Apache-2.0:** retain its license and applicable notices, identify modified
  files and preserve required NOTICE attribution. It does not grant a general
  trademark license. [Authoritative license](https://www.apache.org/licenses/LICENSE-2.0).
- **Fonts and assets:** keep their own license texts and attribution. SIL OFL
  fonts have separate redistribution and reserved-font-name rules. Other
  materials may use ISC, BSD, CC0 or attribution licenses; consult the per-app
  NOTICE and ATTRIBUTION/ASSETS documents before replacing or modifying them.
- **MPL-2.0 components:** DeckCraft, FilmCraft, EffectCraft and SoundCraft use
  Symphonia; CADCraft uses acadrust.
  Preserve notices and access to the corresponding covered source, including
  changes if those components are modified. Do not call these dependencies MIT.
- **LightCraft:** its SAM3 port is Apache-2.0-only; optional model weights and
  datasets have their own terms. Optional downloads are not granted a license
  by the portal. No inference weights for those editor features are added by
  this deployment.
- **ArtCraft marks:** the original `docs/brand/LICENSE-brand.txt` is a restricted
  trademark permission, not an open-source license. A modified or derived
  version must remove the marks or obtain permission. Never market Liberty as
  an official ArtCraft product or imply endorsement. Plain-text upstream
  attribution is retained. Review embedded branding before distributing any
  rebuilt or modified editor.

## Prepared editor assets

The installer verifies original archives against `upstream.lock.json` before
preparing the Liberty integration. [`branding.lock.json`](../branding.lock.json)
records the reviewed embedded graphics and their exact source commits, byte
ranges and before/after hashes. Independent Liberty artwork replaces seven
restricted graphic payloads across FilmCraft, PdfCraft, EffectCraft and
DesignCraft. The inventory covers twelve complete product-identity/community
labels, retaining plain-text source attribution. Nine installed upstream
binaries receive data-only preparation; FigCraft's two labels are changed in
its source build described below. DeckCraft, PhotoCraft and LightCraft have a
separate reviewed, unmodified-binary inventory.

The data-only preparation is a deterministic transformation of pinned binary
data, not a Rust rebuild. Every replacement must fit entirely inside
a WebAssembly data segment and retain its byte length. Executable sections,
data addresses, legal notices, plain-text upstream attribution and separately
licensed application icons are preserved. SVG/path padding is whitespace; PNG
padding is a valid private ancillary chunk before IEND. Unexpected bytes,
hashes, counts, versions or segment boundaries stop installation.

Prepared bundles record their changes in `LIBERTY-MODIFICATIONS.json`. HTML
integrity references and compressed copies are updated with the modified data.
The served HTML also loads the independent integration adapter. These are
modified integrations, not official upstream builds. Preserve both original
notices and the modification records when redistributing them. Recheck embedded
graphics and source render paths before any upstream update; a matching filename
or unchanged executable section alone does not establish license compliance.

### FigCraft browser file I/O

The pinned FigCraft web release does not implement its native save/open picker
services. Liberty builds this editor from the exact upstream commit with
[`patches/figcraft-web/`](../patches/figcraft-web/) and the fail-closed
[`patch_figcraft_web.py`](../scripts/patch_figcraft_web.py) source changes.
Those editor changes are **MIT OR Apache-2.0**, like the upstream editor, and
preserve original copyright and license notices. Unlike the data-only changes
above, this build intentionally changes executable code.

[`figcraft-build.lock.json`](../figcraft-build.lock.json) records the original
source archive, pinned Rust image/toolchain, wasm-bindgen, font source, patch
inputs and compiled assets. [`build_figcraft_web.sh`](../scripts/build_figcraft_web.sh)
checks downloaded archives, applies exact source anchors, runs the Rust hook
tests and builds with Cargo `--locked`. The original engine still encodes the
project and exported images; the added browser service handles their bytes.
Imports use the existing host picker and remain disabled in the public demo.
The 100 MiB encoded-file limit is not a bound on all decoding/rendering memory.
This patch enables native project opening/saving and engine exports, not every
desktop service. Auxiliary pickers for imports, libraries and plugins remain
unavailable in this web build and report that limitation explicitly.

Installation verifies the reviewed compiled files and current patch inputs,
preserves the original bundle's notices, and records the source-build changes
in `LIBERTY-MODIFICATIONS.json`. Deep runtime diagnostics check the build lock
and installed file hashes. The optional local bundle-image build argument may
reuse already-built assets, but does not bypass these checks. The portal source
offer contains the patch and build recipe as well as the upstream source URL.

Liberty's portal, isolated
hosting, startup handling, export bridge and lightweight text mode are separate
integration code. A binary hash verifies the selected artifact, not its complete
license compliance or equivalence to a source build. Do not describe the
lightweight mode as an upstream WordCraft release.

Liberty's corresponding portal source is available at `/source.zip`, including
integration and build scripts. Keep this offer available when deploying modified
portal code. The AGPL network-source obligation is separate from the upstream
editors' licenses. This inventory reviews the pinned editor declarations and
listed third-party notices; it is not an exhaustive audit of every transitive
Rust dependency or legal advice. Recheck it whenever updating an editor.

## Português brasileiro

Os 13 editores declaram **MIT OU Apache-2.0** para seu código principal. Essas
licenças permitem modificar, integrar e redistribuir, cumpridas suas condições.
A AGPL do Liberty não substitui as licenças dos programas, dependências,
fontes, modelos ou marcas.

Mantenha os textos originais, copyrights, NOTICE e atribuições. Em alterações
sob Apache-2.0, identifique os arquivos modificados. Fontes OFL têm regras
próprias; Symphonia (DeckCraft, FilmCraft, EffectCraft e SoundCraft) e acadrust
(CADCraft) são componentes MPL-2.0, com obrigação de manter
acesso ao fonte correspondente. O port SAM3 do LightCraft é Apache-2.0 apenas;
pesos e dados opcionais precisam de análise separada.

As marcas ArtCraft **não são código aberto**. Versões modificadas ou derivadas
precisam removê-las ou obter autorização. O Liberty não deve ser apresentado
como produto oficial ou endossado pelo upstream. O instalador confere primeiro
os arquivos originais. O inventário `branding.lock.json` fixa sete substituições
gráficas em FilmCraft, PdfCraft, EffectCraft e DesignCraft, com arte própria,
commits, posições e hashes de entrada/saída. O inventário cobre doze rótulos
completos de identidade do produto/comunidade, preservando atribuição textual.
Nove binários instalados recebem preparação apenas de dados; os dois rótulos
do FigCraft são alterados no seu build de fonte. DeckCraft, PhotoCraft e
LightCraft constam em inventário revisado de binários não modificados.

A preparação de dados altera somente segmentos WASM, preservando tamanho e
endereços; essa etapa não recompila Rust nem modifica instruções executáveis.
Licenças, copyrights, atribuições textuais e ícones dos aplicativos com licenças
próprias permanecem. Uma divergência de hash, versão, contagem ou limites impede
a instalação. Referências de integridade HTML e cópias comprimidas são
atualizadas; `LIBERTY-MODIFICATIONS.json` registra as alterações. O HTML também
carrega o adaptador de integração. São integrações modificadas, não builds
oficiais. Preserve os avisos originais e esses registros, e repita a revisão de
assets e caminhos de desenho ao atualizar cada editor.

O FigCraft é uma exceção explícita: seu build web original não implementa os
serviços de abrir/salvar. O Liberty recompila o commit fixado com as alterações
em `patches/figcraft-web/`, licenciadas MIT OU Apache-2.0, preservando os avisos
originais. Esse build modifica código executável. O lock `figcraft-build.lock.json`
registra fonte, toolchain/imagem Rust, wasm-bindgen, fontes, patches e arquivos
compilados. O script confere arquivos baixados, aplica âncoras exatas, executa
testes Rust e usa Cargo `--locked`. Os encoders continuam sendo os do programa
original. A abertura usa o seletor existente e permanece bloqueada na demo;
100 MiB limita bytes codificados, não toda a memória de decodificação/renderização.
O patch habilita abrir/salvar projetos e exportações nativas, não todos os
serviços de desktop. Seletores auxiliares de importação, bibliotecas e plugins
continuam indisponíveis neste build web, com aviso explícito.
Instalação e diagnóstico profundo conferem o lock e os hashes. Reusar uma imagem
local com os arquivos compilados não dispensa essas verificações. O `/source.zip`
inclui os patches, a receita de build e a URL do fonte original.

A tabela acima identifica versão, fonte e avisos de cada editor. A revisão cobre
essas declarações e os materiais listados, não uma auditoria exaustiva de todas
as dependências transitivas. Preserve a oferta de código do portal em
`/source.zip`; o inventário não constitui aconselhamento jurídico.
