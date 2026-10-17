// SPDX-License-Identifier: MIT OR Apache-2.0
#[path = "browser_io.rs"]
mod browser_io;

#[test]
fn no_host_fails_closed() {
    assert!(browser_io::read("missing.figcraft").is_err());
    assert!(browser_io::write("missing.png", b"bytes").is_err());
}

#[test]
fn host_receives_real_bytes_and_failures_propagate() {
    browser_io::install(
        |_| Ok(b"native project bytes".to_vec()),
        |name, bytes| {
            assert_eq!(name, "design.png");
            assert_eq!(bytes, b"real encoded image");
            Err("download refused".into())
        },
    );
    assert_eq!(browser_io::read("design.figcraft").unwrap(), b"native project bytes");
    assert_eq!(browser_io::write("design.png", b"real encoded image"), Err("download refused".into()));
}

#[test]
fn filenames_are_bounded_basenames() {
    assert_eq!(browser_io::file_name("../private/design.png"), "design.png");
    assert_eq!(browser_io::file_name("C:\\private\\draft.figcraft"), "draft.figcraft");
    assert_eq!(browser_io::file_name("bad\nname.svg"), "badname.svg");
    assert!(browser_io::file_name(&"x".repeat(1000)).chars().count() <= 180);
}

#[test]
fn empty_and_oversized_files_fail_before_write() {
    browser_io::install(|_| Ok(vec![0; browser_io::MAX_BYTES + 1]), |_, _| panic!("must not write rejected bytes"));
    assert!(browser_io::write("empty.png", b"").is_err());
    assert!(browser_io::write("large.png", &vec![0; browser_io::MAX_BYTES + 1]).is_err());
    assert!(browser_io::read("large.figcraft").is_err());
}
