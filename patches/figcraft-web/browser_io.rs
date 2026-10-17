// SPDX-License-Identifier: MIT OR Apache-2.0
//! Bounded browser-host file hooks; no browser dependency enters the engine.
use std::cell::Cell;

pub const MAX_BYTES: usize = 100 * 1024 * 1024;
type Reader = fn(&str) -> Result<Vec<u8>, String>;
type Writer = fn(&str, &[u8]) -> Result<(), String>;
thread_local! {
    static READER: Cell<Option<Reader>> = const { Cell::new(None) };
    static WRITER: Cell<Option<Writer>> = const { Cell::new(None) };
}

pub fn install(reader: Reader, writer: Writer) {
    READER.set(Some(reader));
    WRITER.set(Some(writer));
}

pub fn read(path: &str) -> Result<Vec<u8>, String> {
    let bytes = READER.get().ok_or("No browser file reader installed")?(path)?;
    if bytes.len() > MAX_BYTES { return Err("File exceeds the 100 MiB limit".into()); }
    Ok(bytes)
}

pub fn write(path: &str, bytes: &[u8]) -> Result<(), String> {
    if bytes.is_empty() || bytes.len() > MAX_BYTES {
        return Err("Export must contain between 1 byte and 100 MiB".into());
    }
    WRITER.get().ok_or("No browser file writer installed")?(path, bytes)
}

pub fn file_name(path: &str) -> String {
    let name: String = path.rsplit(['/', '\\']).next().unwrap_or("")
        .chars().filter(|c| !c.is_control()).take(180).collect();
    if name.trim().is_empty() || matches!(name.as_str(), "." | "..") {
        "Untitled.figcraft".into()
    } else { name }
}
