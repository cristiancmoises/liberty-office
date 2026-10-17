// SPDX-License-Identifier: MIT OR Apache-2.0
//! Real engine bytes flow to browser downloads; imports use the existing host picker.
use std::cell::{Cell, RefCell};
use figcraft_engine::browser_io::{self, MAX_BYTES};
use wasm_bindgen::{JsCast, JsValue, closure::Closure};
use wasm_bindgen_futures::{JsFuture, spawn_local};

type Opened = Result<(String, Vec<u8>), String>;
thread_local! {
    static OPENING: Cell<bool> = const { Cell::new(false) };
    static NEXT_ID: Cell<u64> = const { Cell::new(0) };
    static PENDING: RefCell<Option<Opened>> = const { RefCell::new(None) };
    static INPUT: RefCell<Option<(String, Vec<u8>)>> = const { RefCell::new(None) };
}

pub fn install() { browser_io::install(read, download); }

fn read(path: &str) -> Result<Vec<u8>, String> {
    INPUT.with(|input| match input.borrow_mut().take() {
        Some((name, bytes)) if name == path => Ok(bytes),
        _ => Err("Choose the file again using File > Open".into()),
    })
}

fn js_error(error: JsValue) -> String {
    error.as_string().unwrap_or_else(|| format!("Browser file operation failed: {error:?}"))
}

pub fn download(path: &str, bytes: &[u8]) -> Result<(), String> {
    let window = web_sys::window().ok_or("No browser window")?;
    let document = window.document().ok_or("No browser document")?;
    let array = js_sys::Array::of1(&js_sys::Uint8Array::from(bytes));
    let blob = web_sys::Blob::new_with_u8_array_sequence(&array).map_err(js_error)?;
    let url = web_sys::Url::create_object_url_with_blob(&blob).map_err(js_error)?;
    let result = (|| {
        let anchor = document.create_element("a").map_err(js_error)?
            .dyn_into::<web_sys::HtmlAnchorElement>().map_err(|error| js_error(error.into()))?;
        anchor.set_href(&url);
        anchor.set_download(&browser_io::file_name(path));
        // The Liberty bridge observes the original Blob and retains the local recovery copy.
        anchor.click();
        Ok(())
    })();
    let revoke_url = url.clone();
    let revoke = Closure::once_into_js(move || { let _ = web_sys::Url::revoke_object_url(&revoke_url); });
    if result.is_err() || window.set_timeout_with_callback_and_timeout_and_arguments_0(revoke.unchecked_ref(), 5000).is_err() {
        let _ = web_sys::Url::revoke_object_url(&url);
    }
    result
}

fn call_method(receiver: &JsValue, name: &str) -> Result<JsValue, String> {
    let function = js_sys::Reflect::get(receiver, &JsValue::from_str(name)).map_err(js_error)?
        .dyn_into::<js_sys::Function>().map_err(js_error)?;
    function.call0(receiver).map_err(js_error)
}

pub fn request_open(context: egui::Context) {
    if OPENING.replace(true) { return; }
    // Call the host picker, not a hidden upload route. Demo mode rejects this exact API.
    let picker = web_sys::window().ok_or_else(|| "No browser window".to_string())
        .and_then(|window| call_method(window.as_ref(), "showOpenFilePicker"));
    spawn_local(async move {
        let result = async {
            let handles = JsFuture::from(js_sys::Promise::resolve(&picker?)).await.map_err(js_error)?;
            let first = js_sys::Array::from(&handles).get(0);
            if first.is_undefined() { return Err("No file selected".into()); }
            let file = JsFuture::from(js_sys::Promise::resolve(&call_method(&first, "getFile")?)).await.map_err(js_error)?
                .dyn_into::<web_sys::File>().map_err(js_error)?;
            if file.size() > MAX_BYTES as f64 { return Err("File exceeds the 100 MiB limit".into()); }
            let buffer = JsFuture::from(file.array_buffer()).await.map_err(js_error)?;
            let bytes = js_sys::Uint8Array::new(&buffer).to_vec();
            if bytes.len() > MAX_BYTES { return Err("File exceeds the 100 MiB limit".into()); }
            let id = NEXT_ID.get().wrapping_add(1); NEXT_ID.set(id);
            Ok((format!("opened-{id}/{}", browser_io::file_name(&file.name())), bytes))
        }.await;
        PENDING.with(|pending| *pending.borrow_mut() = Some(result));
        OPENING.set(false);
        context.request_repaint();
    });
}

pub fn unsupported_picker(context: egui::Context) {
    if !OPENING.get() {
        PENDING.with(|pending| *pending.borrow_mut() = Some(Err("This import operation is unavailable in the web build. Use File > Open to open a document.".into())));
        context.request_repaint();
    }
}

pub fn finish_open(app: &mut figcraft_ui_egui::FigApp) {
    let pending = PENDING.with(|pending| pending.borrow_mut().take());
    match pending {
        Some(Ok((path, bytes))) => {
            INPUT.with(|input| *input.borrow_mut() = Some((path.clone(), bytes)));
            if app.run("file.open", serde_json::json!({"path": path})).is_some() {
                app.ui.home = false;
            }
            INPUT.with(|input| input.borrow_mut().take());
        }
        Some(Err(error)) => app.toast(error),
        None => {}
    }
}
