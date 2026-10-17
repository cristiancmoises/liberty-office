#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Apply fail-closed input-handoff changes to the pinned GridCraft source."""

import hashlib
import sys
from pathlib import Path

SOURCE_COMMIT = "d9d09f0baa912e88c5111107903fc8c640214b57"
SOURCE_SHA256 = "3f4fc387e910a3a4c6e435f33b9b123abb6d3347399d589f9b791a9f53c50b25"
ORIGINALS = {
    "crates/ui-egui/src/grid.rs": "939ee0012ca201d3751f4f1fc087d51f64870dc42ab4f3c700211933f9b3c570",
    "crates/ui-egui/src/formula_bar.rs": "45ce890b31b0aaf3f4df30a7acd83296c119f53af8195ae07390b0c56ab5c5bb",
    "crates/ui-egui/src/lib.rs": "d8bf5aee01f7b0728e67343fe560d8a71ab2e8e8bff77ea93eb6bf2b91642939",
    "crates/ui-egui/src/dialogs.rs": "617f673ba0d346f6891e860c63e0dac1ddd433e1c684de27ed17890f8e758ad2",
    "Cargo.lock": "cf9d5d467a0298265ff866b05d806f503785c15de1689c69a666cc04bf01b84f",
}


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one patch anchor: {old[:80]!r}")
    return source.replace(old, new, 1)


def patch(root, payload, tests_only=False):
    contents = {}
    for name, expected in ORIGINALS.items():
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Pinned GridCraft source mismatch: {name}")
        contents[name] = raw.decode()
    contents["Cargo.lock"] += """
[[package]]
name = "liberty-gridcraft-input-tests"
version = "0.1.0"
dependencies = [
 "egui",
 "gridcraft-engine",
 "gridcraft-ui-egui",
 "serde_json",
]
"""
    contents["crates/liberty-input-tests/Cargo.toml"] = (
        payload / "input-tests.Cargo.toml"
    ).read_text()
    contents["crates/liberty-input-tests/src/lib.rs"] = (
        payload / "input_tests.rs"
    ).read_text()
    if not tests_only:

        def change(name, old, new):
            contents[name] = replace_once(contents[name], old, new)

        change(
            "crates/ui-egui/src/lib.rs",
            "pub mod keymap;",
            "mod input_handoff;\npub mod keymap;",
        )
        change(
            "crates/ui-egui/src/lib.rs",
            "    pub synthetic: std::collections::VecDeque<Vec<egui::Event>>,",
            "    pub synthetic: std::collections::VecDeque<Vec<egui::Event>>,\n    pub(crate) deferred_edit_input: Vec<egui::Event>,",
        )
        change(
            "crates/ui-egui/src/lib.rs",
            "            synthetic: Default::default(),",
            "            synthetic: Default::default(),\n            deferred_edit_input: Vec::new(),",
        )
        change(
            "crates/ui-egui/src/lib.rs",
            "    pub fn raw_input_hook(&mut self, raw: &mut egui::RawInput) {",
            """    pub fn raw_input_hook(&mut self, raw: &mut egui::RawInput) {
        // Replay ordered keyboard suffixes before egui derives this frame's state.
        if !self.deferred_edit_input.is_empty() {
            let mut pending = std::mem::take(&mut self.deferred_edit_input);
            pending.append(&mut raw.events);
            raw.events = pending;
        }""",
        )
        change(
            "crates/ui-egui/src/grid.rs",
            "    for ev in events {",
            "    for (event_index, ev) in events.into_iter().enumerate() {",
        )
        change(
            "crates/ui-egui/src/grid.rs",
            "                app.begin_edit(Some(text), false);",
            """                // This text initializes the edit exactly once. The new focused TextEdit
                // owns the remaining events; do not replay the initialization prefix.
                ctx.input_mut(|input| { input.events.drain(..=event_index); });
                app.begin_edit(Some(text), false);""",
        )
        change(
            "crates/ui-egui/src/formula_bar.rs",
            "    if has_focus && mine {",
            "    if has_focus && mine {\n        crate::input_handoff::defer_after_boundary(ui.ctx(), &mut app.deferred_edit_input);",
        )
        change(
            "crates/ui-egui/src/formula_bar.rs",
            "    // The text widget.\n",
            """    // Hand off focus/caret before TextEdit reads this frame's remaining events.
    let synced = mine && (ed.request_focus || ed.sync_caret);
    if synced {
        if ed.request_focus {
            ui.memory_mut(|memory| memory.request_focus(id));
        }
        let mut state = TextEdit::load_state(ui.ctx(), id).unwrap_or_default();
        state.cursor.set_char_range(Some(egui::text::CCursorRange::one(egui::text::CCursor::new(ed.caret))));
        state.store(ui.ctx(), id);
        ed.request_focus = false;
        ed.sync_caret = false;
    }
    // The text widget.
""",
        )
        change(
            "crates/ui-egui/src/formula_bar.rs",
            "    let mut output = edit",
            "    let output = edit",
        )
        change(
            "crates/ui-egui/src/formula_bar.rs",
            """    let synced = mine && (ed.request_focus || ed.sync_caret);
    if synced {
        if ed.request_focus {
            resp.request_focus();
        }
        ed.request_focus = false;
        ed.sync_caret = false;
        let cursor = egui::text::CCursor::new(ed.caret);
        output.state.cursor.set_char_range(Some(egui::text::CCursorRange::one(cursor)));
        output.state.store(ui.ctx(), id);
    } else if resp.clicked() || resp.gained_focus() {""",
            "    if !synced && (resp.clicked() || resp.gained_focus()) {",
        )
        change(
            "crates/ui-egui/src/formula_bar.rs",
            "    if !synced && let Some(r) = output.cursor_range {",
            "    if let Some(r) = output.cursor_range {",
        )
        change(
            "crates/ui-egui/src/dialogs.rs",
            "A clean-room, open-source, Rust-native spreadsheet. Part of ArtCraft.",
            "Independent integration based on GridCraft by the ArtCraft team.",
        )
        contents["crates/ui-egui/src/input_handoff.rs"] = (
            payload / "input_handoff.rs"
        ).read_text()
    for name, content in contents.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)


if __name__ == "__main__":
    patch(
        Path(sys.argv[1]),
        Path(__file__).resolve().parent.parent / "patches/gridcraft-web",
        "--tests-only" in sys.argv[2:],
    )
