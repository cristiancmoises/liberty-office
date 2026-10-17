#!/usr/bin/env python3
"""Apply reviewed, fail-closed FigCraft browser I/O changes to its pinned source."""

import hashlib
import sys
from pathlib import Path

SOURCE_COMMIT = "833f0d2c27f0acbae5394848930ae531fc89c724"
SOURCE_SHA256 = "f327701beaf7a025a0f124c8551472ab998d2b07baf3949c8a2d86ebcf457e59"
ORIGINALS = {
    "crates/engine/src/cmd/file.rs": "c06bc6c9564dd068829283815f2d95b2e78e24faa47fa7d682b777f14a4b7377",
    "crates/engine/src/lib.rs": "187fe15e514dc8e179235f88641b3265684112d90604cbff6c7b03d3acb15740",
    "apps/figcraft-web/src/web.rs": "594def69876eb10da36d646417f66fc3a1a813ab6e1a5177c5a28b846039f90d",
    "apps/figcraft-web/Cargo.toml": "b260dbf2df4b3cee15e55e33b98535b91192fc7b3ec448184b462d14ccf9cc24",
    "apps/figcraft-web/src/main.rs": "3aa5fefe6fdaa5e6166119ceeb83f10b45cf3eabefa8af7fcde7c94a3dd5d3bd",
    "Cargo.lock": "927ab98bf28199b5f407edb250accbfd55d512a8d98206a331bc0795fcaa3569",
    "crates/ui-egui/src/dialogs.rs": "f73beeb20d64cd0ff63efd4cc0b5e63b5d11de10630ca86a4b6baac7bf949019",
    "crates/ui-egui/src/lib.rs": "97752e091fcc5bce141b38260d72276a527dc6e105c0fbfb5dc74c2b342533fa",
}


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one patch anchor: {old[:80]!r}")
    return source.replace(old, new, 1)


def patch(root, payload):
    contents = {}
    for name, expected in ORIGINALS.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Pinned FigCraft source mismatch: {name}")
        contents[name] = raw.decode()

    def change(name, old, new):
        contents[name] = replace_once(contents[name], old, new)

    change(
        "crates/ui-egui/src/lib.rs",
        "pub trait Services {",
        "pub trait Services {\n    /// Return true when the host owns asynchronous File > Open.\n    fn open_file_async(&mut self) -> bool { false }",
    )
    change(
        "crates/ui-egui/src/lib.rs",
        "    pub fn open_dialog(&mut self) {",
        "    pub fn open_dialog(&mut self) {\n        if self.services.open_file_async() { return; }",
    )

    change(
        "crates/engine/src/lib.rs",
        "pub mod al_keys;",
        '#[cfg(target_arch = "wasm32")]\npub mod browser_io;\npub mod al_keys;',
    )
    change(
        "crates/engine/src/cmd/file.rs",
        'fn read(path: &str) -> Result<Vec<u8>> {\n    Err(EngineError::Other(format!("{path}: no file system in the browser")))\n}',
        "fn read(path: &str) -> Result<Vec<u8>> {\n    crate::browser_io::read(path).map_err(EngineError::Other)\n}",
    )
    change(
        "crates/engine/src/cmd/file.rs",
        'pub(crate) fn write(path: &str, _bytes: &[u8]) -> Result<()> {\n    Err(EngineError::Other(format!("{path}: no file system in the browser")))\n}',
        "pub(crate) fn write(path: &str, bytes: &[u8]) -> Result<()> {\n    crate::browser_io::write(path, bytes).map_err(EngineError::Other)\n}",
    )
    change(
        "apps/figcraft-web/src/main.rs",
        "mod web;",
        'mod web;\n#[cfg(target_arch = "wasm32")]\nmod web_file_io;',
    )
    change(
        "apps/figcraft-web/src/main.rs",
        "//! - no native file dialogs yet: the session starts with one new document;",
        "//! - bounded host file picker and native-format browser downloads;",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "pub fn start() {",
        "pub fn start() {\n    crate::web_file_io::install();",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "WebServices { reduce_motion }",
        "WebServices { reduce_motion, context: cc.egui_ctx.clone() }",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "        self.fig.ui(ui);",
        "        crate::web_file_io::finish_open(&mut self.fig);\n        self.fig.ui(ui);",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "/// Browser services. File dialogs return nothing for now (the trait's defaults); the clipboard\n/// goes through egui's own web clipboard handling.",
        "/// Browser services use bounded host file I/O; the clipboard uses egui's web handling.",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "struct WebServices {",
        "struct WebServices {\n    context: egui::Context,",
    )
    change(
        "apps/figcraft-web/src/web.rs",
        "impl Services for WebServices {",
        """impl Services for WebServices {
    fn pick_save(&mut self, _title: &str, name: &str, _exts: &[&str]) -> Option<std::path::PathBuf> {
        Some(figcraft_engine::browser_io::file_name(name).into())
    }
    fn open_file_async(&mut self) -> bool {
        crate::web_file_io::request_open(self.context.clone());
        true
    }
    fn pick_open(&mut self, _title: &str, _exts: &[&str]) -> Option<std::path::PathBuf> {
        crate::web_file_io::unsupported_picker(self.context.clone());
        None
    }""",
    )
    change(
        "apps/figcraft-web/Cargo.toml",
        "log = { workspace = true }",
        "log = { workspace = true }\nserde_json = { workspace = true }",
    )
    change(
        "apps/figcraft-web/Cargo.toml",
        'wasm-bindgen = "0.2"',
        'js-sys = "0.3"\nwasm-bindgen = "0.2"',
    )
    change(
        "apps/figcraft-web/Cargo.toml",
        '"GamepadMappingType"]',
        '"GamepadMappingType", "Blob", "Url", "File", "HtmlAnchorElement", "HtmlElement"]',
    )
    lock_start = contents["Cargo.lock"].index('name = "figcraft-web"\n')
    lock_end = contents["Cargo.lock"].index("\n[[package]]", lock_start)
    block = contents["Cargo.lock"][lock_start:lock_end]
    block = replace_once(block, ' "log",', ' "js-sys",\n "log",\n "serde_json",')
    contents["Cargo.lock"] = (
        contents["Cargo.lock"][:lock_start] + block + contents["Cargo.lock"][lock_end:]
    )
    # Only the two reviewed runtime labels; copyrights, source credits and translations stay.
    change(
        "crates/ui-egui/src/dialogs.rs",
        "Interface design and prototyping. A free, open-source, clean-room design tool written from scratch in Rust, part of the ArtCraft Crafting Apps.",
        "Independent Liberty integration based on FigCraft, an open-source interface design and prototyping tool.",
    )
    change(
        "crates/ui-egui/src/dialogs.rs",
        "Dual-licensed MIT OR Apache-2.0. Made by the ArtCraft team and community.",
        "Dual-licensed MIT OR Apache-2.0. Based on the ArtCraft team's work.",
    )
    contents["crates/engine/src/browser_io.rs"] = (
        payload / "browser_io.rs"
    ).read_text()
    contents["apps/figcraft-web/src/web_file_io.rs"] = (
        payload / "web_file_io.rs"
    ).read_text()
    for name, content in contents.items():
        (root / name).write_text(content)


if __name__ == "__main__":
    patch(
        Path(sys.argv[1]),
        Path(__file__).resolve().parent.parent / "patches/figcraft-web",
    )
