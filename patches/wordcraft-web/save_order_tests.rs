// SPDX-License-Identifier: MIT OR Apache-2.0
//! Real WordCraft canvas events and saved DOCX snapshots, without a renderer.
use super::*;
use crate::Services;
use std::{cell::RefCell, rc::Rc};
use wordcraft_doc::{Document, StoryRef};
use wordcraft_engine::Session;

type Downloads = Rc<RefCell<Vec<(String, Vec<u8>)>>>;

fn app() -> (WordApp, Downloads) {
    let downloads: Downloads = Default::default();
    let sink = downloads.clone();
    let services = Services {
        download: Some(Box::new(move |name, bytes| {
            sink.borrow_mut().push((name.into(), bytes.to_vec()));
            Ok(())
        })),
        ..Default::default()
    };
    let mut app = WordApp::new(Session::new(Document::new()), services);
    app.session.path = Some("save-order.docx".into());
    app.run("text.insert", json!({"text":"Before"})).unwrap();
    (app, downloads)
}

fn key(key: Key, modifiers: Modifiers) -> egui::Event {
    egui::Event::Key {
        key,
        physical_key: Some(key),
        pressed: true,
        repeat: false,
        modifiers,
    }
}

fn frame(app: &mut WordApp, mut events: Vec<egui::Event>, modifiers: Modifiers) {
    // egui 0.36 carries modifier changes in the ordered event queue, not RawInput.
    let shortcut = events
        .iter()
        .position(|event| matches!(event, egui::Event::Key { .. }))
        .unwrap_or(events.len());
    events.insert(shortcut, egui::Event::ModifiersChanged(modifiers));
    egui::Context::default()
        .run_ui(
            egui::RawInput {
                events,
                ..Default::default()
            },
            |ui| {
                assert_eq!(ui.ctx().input(|input| input.modifiers), modifiers);
                canvas_events(app, ui.ctx());
            },
        )
        .drop_without_applying_deltas();
}

#[test]
fn queued_text_is_included_in_the_same_frame_save_snapshot() {
    let (mut app, downloads) = app();
    frame(
        &mut app,
        vec![
            egui::Event::Text(".".into()),
            key(Key::S, Modifiers::COMMAND),
        ],
        Modifiers::COMMAND,
    );
    assert_eq!(app.session.doc.plain_text(StoryRef::Body), "Before.");
    let (name, bytes) = downloads.borrow_mut().pop().expect("native save callback");
    let saved = wordcraft_engine::io::open_bytes(&name, &bytes).unwrap();
    assert_eq!(saved.plain_text(StoryRef::Body), "Before.");
}

#[test]
fn several_queued_text_events_are_not_dropped_by_a_later_modifier() {
    let (mut app, downloads) = app();
    frame(
        &mut app,
        vec![
            egui::Event::Text(" café".into()),
            egui::Event::Text("!".into()),
            key(Key::S, Modifiers::COMMAND),
        ],
        Modifiers::COMMAND,
    );
    assert_eq!(app.session.doc.plain_text(StoryRef::Body), "Before café!");
    let (name, bytes) = downloads.borrow_mut().pop().unwrap();
    assert_eq!(
        wordcraft_engine::io::open_bytes(&name, &bytes)
            .unwrap()
            .plain_text(StoryRef::Body),
        "Before café!"
    );
}

#[test]
fn save_shortcut_without_text_does_not_type_its_key() {
    let (mut app, downloads) = app();
    frame(
        &mut app,
        vec![key(Key::S, Modifiers::COMMAND)],
        Modifiers::COMMAND,
    );
    assert_eq!(app.session.doc.plain_text(StoryRef::Body), "Before");
    assert_eq!(downloads.borrow().len(), 1);
}

#[test]
fn empty_and_control_text_are_still_rejected() {
    let (mut app, _) = app();
    frame(
        &mut app,
        vec![
            egui::Event::Text("".into()),
            egui::Event::Text("\0\n".into()),
        ],
        Modifiers::NONE,
    );
    assert_eq!(app.session.doc.plain_text(StoryRef::Body), "Before");
}

#[test]
fn queued_equation_text_is_not_dropped_by_a_later_modifier() {
    let (mut app, _) = app();
    app.run("document.setText", json!({"text":""})).unwrap();
    app.run("insert.equation", json!({})).unwrap();
    assert!(app.session.math.is_some());
    frame(
        &mut app,
        vec![egui::Event::Text("x".into())],
        Modifiers::COMMAND,
    );
    assert_eq!(app.run("equation.get", json!({})).unwrap()["linear"], "x");
}
