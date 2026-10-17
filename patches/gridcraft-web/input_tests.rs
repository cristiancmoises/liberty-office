// SPDX-License-Identifier: MIT OR Apache-2.0
//! Actual GridCraft UI and engine, driven by deterministic single-frame egui events.
#[cfg(test)]
mod tests {
    use egui::{Context, Event, Key, Modifiers, RawInput, Rect, Vec2};
    use gridcraft_engine::{Session, core::CellRef};
    use gridcraft_ui_egui::SheetApp;

    fn frame(ctx: &Context, app: &mut SheetApp, events: Vec<Event>) {
        let mut input = RawInput {
            screen_rect: Some(Rect::from_min_size(
                Default::default(),
                Vec2::new(1200.0, 800.0),
            )),
            events,
            ..Default::default()
        };
        app.raw_input_hook(&mut input);
        let mut output = ctx.run_ui(input, |ui| {
            app.logic(ui.ctx());
            app.ui(ui);
        });
        // No renderer is involved in these UI/engine state tests. Browser tests
        // exercise the actual GPU output; explicitly acknowledge texture deltas.
        output.textures_delta.clear();
    }

    fn ready() -> (Context, SheetApp) {
        let ctx = Context::default();
        let mut session = Session::new();
        session.new_workbook();
        let mut app = SheetApp::new(session, Default::default());
        for _ in 0..6 {
            frame(&ctx, &mut app, vec![]);
        }
        assert!(app.editor.is_none());
        (ctx, app)
    }

    fn text(value: &str) -> Event {
        Event::Text(value.into())
    }
    fn key(key: Key) -> Event {
        Event::Key {
            key,
            physical_key: Some(key),
            pressed: true,
            repeat: false,
            modifiers: Modifiers::NONE,
        }
    }
    fn value(app: &SheetApp, cell: &str) -> String {
        let document = app.session.active().unwrap();
        document
            .wb
            .active()
            .unwrap()
            .cell(CellRef::parse(cell).unwrap())
            .map(|cell| cell.input_text())
            .unwrap_or_default()
    }
    fn selected(app: &SheetApp) -> String {
        app.session.active().unwrap().selection.active.a1()
    }
    fn settle(ctx: &Context, app: &mut SheetApp) {
        for _ in 0..4 {
            frame(ctx, app, vec![]);
        }
    }

    #[test]
    fn first_frame_text_enter_keeps_every_character_exactly_once() {
        let (ctx, mut app) = ready();
        frame(&ctx, &mut app, vec![text("4"), text("2"), key(Key::Enter)]);
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "42");
        assert_eq!(selected(&app), "A2");
        assert!(app.editor.is_none());
    }

    #[test]
    fn first_frame_tab_commits_exact_text_and_moves_right() {
        let (ctx, mut app) = ready();
        frame(&ctx, &mut app, vec![text("4"), text("2"), key(Key::Tab)]);
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "42");
        assert_eq!(selected(&app), "B1");
    }

    #[test]
    fn first_frame_escape_preserves_existing_cell() {
        let (ctx, mut app) = ready();
        app.session
            .run(
                "cell.set",
                serde_json::json!({"cell":"A1", "input":"original"}),
            )
            .unwrap();
        frame(&ctx, &mut app, vec![text("4"), text("2"), key(Key::Escape)]);
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "original");
        assert_eq!(selected(&app), "A1");
        assert!(app.editor.is_none());
    }

    #[test]
    fn text_after_enter_belongs_to_next_cell_not_previous_edit() {
        let (ctx, mut app) = ready();
        frame(
            &ctx,
            &mut app,
            vec![text("4"), key(Key::Enter), text("2"), key(Key::Enter)],
        );
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "4");
        assert_eq!(value(&app, "A2"), "2");
        assert_eq!(selected(&app), "A3");
    }

    #[test]
    fn first_text_is_not_replayed_on_later_frames() {
        let (ctx, mut app) = ready();
        frame(&ctx, &mut app, vec![text("4")]);
        frame(&ctx, &mut app, vec![text("2"), key(Key::Enter)]);
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "42");
    }

    #[test]
    fn batched_text_keeps_the_caret_after_the_last_character() {
        let (ctx, mut app) = ready();
        frame(&ctx, &mut app, vec![text("4"), text("2")]);
        frame(&ctx, &mut app, vec![text("3"), key(Key::Enter)]);
        settle(&ctx, &mut app);
        assert_eq!(value(&app, "A1"), "423");
    }
}
