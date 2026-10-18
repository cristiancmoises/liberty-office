"""Patch recipe boundaries with synthetic source, not a native build substitute."""

import hashlib

import pytest

from scripts import patch_wordcraft_web as recipe


@pytest.fixture
def source(tmp_path, monkeypatch):
    root, payload = tmp_path / "source", tmp_path / "payload"
    ui = root / "crates/ui-egui/src"
    ui.mkdir(parents=True)
    payload.mkdir()
    keys = """                let m = ctx.input(|i| i.modifiers);
                if m.command || (m.ctrl && !cfg!(target_os = "macos")) {
                    continue;
                }
                    let m = ctx.input(|i| i.modifiers);
                    if !(m.command || t.is_empty() || (m.ctrl && !cfg!(target_os = "macos"))) && t.chars().all(|c| !c.is_control()) {
"""
    dialogs = "A free, open-source word processor written from scratch in Rust.\\nPart of the Crafting Apps from the ArtCraft team."
    (ui / "keys.rs").write_text(keys)
    (ui / "dialogs.rs").write_text(dialogs)
    canvas = "    if app.canvas.focused && !matches!(app.dialog, Some(crate::dialogs::Dialog::SaveChanges { .. })) {\n"
    (ui / "canvas.rs").write_text(canvas)
    (payload / "save_order_tests.rs").write_text("// regression payload\n")
    monkeypatch.setattr(
        recipe, "KEYS_SHA256", hashlib.sha256(keys.encode()).hexdigest()
    )
    monkeypatch.setattr(
        recipe,
        "DIALOGS_SHA256",
        hashlib.sha256(dialogs.encode()).hexdigest(),
        raising=False,
    )
    monkeypatch.setattr(
        recipe,
        "CANVAS_SHA256",
        hashlib.sha256(canvas.encode()).hexdigest(),
        raising=False,
    )
    return root, payload, ui, keys, dialogs


def test_recipe_preserves_fifo_and_distinguishes_the_modified_integration(source):
    root, payload, ui, _, _ = source
    recipe.patch(root, payload)
    assert (ui / "keys.rs").read_text().startswith("// Liberty Office modification:")
    assert "ctx.input(|i| i.modifiers)" not in (ui / "keys.rs").read_text()
    assert (
        "if !t.is_empty() && t.chars().all(|c| !c.is_control())"
        in (ui / "keys.rs").read_text()
    )
    assert (ui / "liberty_save_order_tests.rs").read_bytes() == (
        payload / "save_order_tests.rs"
    ).read_bytes()
    assert (ui / "dialogs.rs").read_text().startswith("// Liberty Office modification:")
    assert (
        (ui / "dialogs.rs")
        .read_text()
        .endswith(
            "Independent Liberty Office integration based on WordCraft by the ArtCraft team."
        )
    )


def test_baseline_injects_only_the_regression_tests(source):
    root, payload, ui, keys, dialogs = source
    recipe.patch(root, payload, tests_only=True)
    assert (ui / "keys.rs").read_text().startswith(keys)
    assert (ui / "dialogs.rs").read_text() == dialogs
    assert (ui / "canvas.rs").read_text().startswith("    if app.canvas.focused &&")


def test_restored_canvas_accepts_text_without_stealing_widget_or_modal_focus(source):
    root, payload, ui, _, _ = source
    recipe.patch(root, payload)
    canvas = (ui / "canvas.rs").read_text()
    assert canvas.startswith("// Liberty Office modification:")
    assert "app.canvas.focused || restoring_focus" in canvas
    assert "app.canvas.want_focus" in canvas
    assert "m.focused().is_none()" in canvas
    assert "app.dialog.is_none()" in canvas and "app.colors.is_none()" in canvas
    assert "!egui::Popup::is_any_open(ui.ctx())" in canvas
    assert "app.file_browser.open.is_none()" in canvas


@pytest.mark.parametrize("name", ["keys.rs", "dialogs.rs", "canvas.rs"])
def test_unrecognized_source_is_rejected_before_any_change(source, name):
    root, payload, ui, _, _ = source
    (ui / name).write_text("unrecognized source")
    before = {path.name: path.read_bytes() for path in ui.iterdir()}
    with pytest.raises(ValueError, match="source mismatch"):
        recipe.patch(root, payload)
    assert {path.name: path.read_bytes() for path in ui.iterdir()} == before
