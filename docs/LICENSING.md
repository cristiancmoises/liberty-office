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

The pinned upstream JS/WASM files remain unchanged, but the served upstream HTML
is instrumented to load the integration adapter. **Brand permission for this
modified-hosting context has not been confirmed.** Unchanged binary hashes do
not resolve that question. Publishing a modified branded editor requires either
permission from the rights holder or a build with those marks removed. Do not
treat this inventory as approval of the current branded integration.

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
como produto oficial ou endossado pelo upstream. Os bundles JS/WASM fixados
permanecem inalterados; integração, interface do portal e modo leve são código
separado. O HTML servido recebe o adaptador de integração: **não há autorização
de marca confirmada para esse contexto modificado**. Hashes inalterados dos
binários não resolvem essa questão. Antes de publicar uma integração modificada
com marcas, obtenha autorização ou prepare um build sem essas marcas.

A tabela acima identifica versão, fonte e avisos de cada editor. A revisão cobre
essas declarações e os materiais listados, não uma auditoria exaustiva de todas
as dependências transitivas. Preserve a oferta de código do portal em
`/source.zip`; o inventário não constitui aconselhamento jurídico.
