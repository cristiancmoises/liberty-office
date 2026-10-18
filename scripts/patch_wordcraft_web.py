#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
"""Preserve ordered text and returning canvas focus in pinned WordCraft source."""

import hashlib
import sys
from pathlib import Path

SOURCE_COMMIT = "fc41918814f62645b6746ed68e71e8c2c2e85d6f"
SOURCE_SHA256 = "ea7a64508f9df85878481f41ad961f8396be0e6a4cf0f9842844a86dc7a48fb6"
KEYS_SHA256 = "c2a24893f378fd770306387893696b73880d03a6c9fd60cd79e2c87746206b55"
DIALOGS_SHA256 = "1670cf523d8882672d16ef55fe1584f08e38b9bf6f3874be414d2fa0ba6eec8e"
CANVAS_SHA256 = "0bd48e26bdd2bf48913818a01f5086f60a2dd72ba63038296ef29d514ccc4cd9"


def patch(root, payload, tests_only=False):
    keys = root / "crates/ui-egui/src/keys.rs"
    original = keys.read_bytes()
    if hashlib.sha256(original).hexdigest() != KEYS_SHA256:
        raise ValueError("Pinned WordCraft keyboard source mismatch")
    dialogs = root / "crates/ui-egui/src/dialogs.rs"
    identity = dialogs.read_bytes()
    if hashlib.sha256(identity).hexdigest() != DIALOGS_SHA256:
        raise ValueError("Pinned WordCraft dialog source mismatch")
    canvas = root / "crates/ui-egui/src/canvas.rs"
    view = canvas.read_bytes()
    if hashlib.sha256(view).hexdigest() != CANVAS_SHA256:
        raise ValueError("Pinned WordCraft canvas source mismatch")
    view = view.decode()
    identity = identity.decode()
    regression = (payload / "save_order_tests.rs").read_bytes()
    source = original.decode()
    if not tests_only:
        replacements = [
            (
                """                let m = ctx.input(|i| i.modifiers);
                if m.command || (m.ctrl && !cfg!(target_os = "macos")) {
                    continue;
                }
""",
                """                // Text was admitted by the host before a later shortcut may
                // change this frame's modifiers. Preserve its queued order.
""",
            ),
            (
                """                    let m = ctx.input(|i| i.modifiers);
                    if !(m.command || t.is_empty() || (m.ctrl && !cfg!(target_os = "macos"))) && t.chars().all(|c| !c.is_control()) {""",
                """                    if !t.is_empty() && t.chars().all(|c| !c.is_control()) {""",
            ),
        ]
        for old, new in replacements:
            if source.count(old) != 1:
                raise ValueError("Unexpected WordCraft text-event patch anchor")
            source = source.replace(old, new, 1)
        old = "    if app.canvas.focused && !matches!(app.dialog, Some(crate::dialogs::Dialog::SaveChanges { .. })) {"
        if view.count(old) != 1:
            raise ValueError("Unexpected WordCraft canvas-focus patch anchor")
        view = view.replace(
            old,
            """    // A chrome click can queue focus restoration for this frame. Its text
    // already belongs to the document, before the response restores egui focus.
    // Never take input from a focused widget, popup, dialog or file browser.
    let restoring_focus = app.canvas.want_focus
        && ui.memory(|m| m.focused().is_none())
        && app.dialog.is_none()
        && app.colors.is_none()
        && !egui::Popup::is_any_open(ui.ctx());
    #[cfg(not(target_arch = "wasm32"))]
    let restoring_focus = restoring_focus && app.file_browser.open.is_none();
    if (app.canvas.focused || restoring_focus) && !matches!(app.dialog, Some(crate::dialogs::Dialog::SaveChanges { .. })) {""",
            1,
        )
        view = (
            "// Liberty Office modification: retain first text while returning focus from document chrome.\n"
            + view
        )
        old = r"A free, open-source word processor written from scratch in Rust.\nPart of the Crafting Apps from the ArtCraft team."
        if identity.count(old) != 1:
            raise ValueError("Unexpected WordCraft integration identity anchor")
        identity = identity.replace(
            old,
            "Independent Liberty Office integration based on WordCraft by the ArtCraft team.",
            1,
        )
        source = (
            "// Liberty Office modification: preserve queued text order before save shortcuts.\n"
            + source
        )
        identity = (
            "// Liberty Office modification: identify the independent integration; preserve upstream legal credits.\n"
            + identity
        )
    addition = '\n#[cfg(test)]\n#[path = "liberty_save_order_tests.rs"]\nmod liberty_save_order_tests;\n'
    keys.write_text(source + addition)
    dialogs.write_text(identity)
    canvas.write_text(view)
    (keys.parent / "liberty_save_order_tests.rs").write_bytes(regression)


if __name__ == "__main__":
    patch(
        Path(sys.argv[1]),
        Path(__file__).resolve().parent.parent / "patches/wordcraft-web",
        "--tests-only" in sys.argv[2:],
    )
