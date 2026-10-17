// SPDX-License-Identifier: MIT OR Apache-2.0
//! Keep text and edit boundaries ordered when the browser batches multiple keys.

/// A commit/cancel belongs at its position in the stream, not after later text.
/// Leave that boundary in this frame for the original editor; resume its suffix
/// next frame after selection/focus has changed. Non-keyboard events are not
/// replayed: egui already derived pointer/focus state from them for this frame.
pub(crate) fn defer_after_boundary(ctx: &egui::Context, deferred: &mut Vec<egui::Event>) {
    let pending = ctx.input_mut(|input| {
        let boundary = input.events.iter().position(|event| {
            matches!(
                event,
                egui::Event::Key {
                    key: egui::Key::Enter | egui::Key::Tab | egui::Key::Escape,
                    pressed: true,
                    ..
                }
            )
        });
        let tail = boundary
            .map(|index| input.events.split_off(index + 1))
            .unwrap_or_default();
        let (pending, other): (Vec<_>, Vec<_>) = tail.into_iter().partition(|event| {
            matches!(
                event,
                egui::Event::Text(_)
                    | egui::Event::Key { .. }
                    | egui::Event::Ime(_)
                    | egui::Event::Paste(_)
                    | egui::Event::Copy
                    | egui::Event::Cut
            )
        });
        input.events.extend(other);
        pending
    });
    if !pending.is_empty() {
        deferred.extend(pending);
        ctx.request_repaint();
    }
}
