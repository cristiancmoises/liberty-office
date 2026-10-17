# SPDX-License-Identifier: MIT OR Apache-2.0
"""Small packaging gates; compilation and native input are checked separately."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "package_gridcraft_web", SCRIPTS / "package_gridcraft_web.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PackageTests(unittest.TestCase):
    def fixture(self, root):
        source, output, fonts = [root / name for name in ("source", "output", "fonts")]
        (source / "apps/gridcraft-web").mkdir(parents=True)
        (source / "assets/app-icon").mkdir(parents=True)
        (source / "assets/app-icon/gridcraft.ico").write_bytes(b"icon")
        (source / "apps/gridcraft-web/index.html").write_text(
            '<link data-trunk rel="icon" href="../../assets/app-icon/gridcraft.ico" /><link data-trunk rel="rust" data-bin="gridcraft-web" data-wasm-opt="z" data-weak-refs />'
        )
        output.mkdir()
        fonts.mkdir()
        for name in ("LICENSE-MIT", "LICENSE-APACHE", "NOTICE"):
            (source / name).write_text(name)
        for name in ("LICENSE-MIT", "LICENSE-APACHE", "ATTRIBUTION.md"):
            (fonts / name).write_text(name)
        for family in ("biz-ud-mincho", "biz-ud-pgothic", "shippori-mincho"):
            (fonts / "fonts" / family).mkdir(parents=True)
            (fonts / "fonts" / family / "OFL.txt").write_text(family)
        (output / "gridcraft-web.js").write_text("export default function init() {}")
        (output / "gridcraft-web_bg.wasm").write_bytes(b"\0asm\x01\0\0\0")
        return source, output, fonts

    def test_generated_entrypoints_and_original_notices_are_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, fonts = self.fixture(Path(directory))
            module.package(source, output, fonts)
            html = (output / "index.html").read_text()
            self.assertIn("./gridcraft-web.js", html)
            self.assertNotIn("data-trunk", html)
            self.assertEqual((output / "NOTICE").read_text(), "NOTICE")
            self.assertTrue(output.with_name("output-build.json").is_file())

    def test_missing_wasm_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, fonts = self.fixture(Path(directory))
            (output / "gridcraft-web_bg.wasm").write_bytes(b"not-wasm")
            with self.assertRaises(ValueError):
                module.package(source, output, fonts)

    def test_additional_liberty_size_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output, fonts = self.fixture(Path(directory))
            with (output / "gridcraft-web_bg.wasm").open("r+b") as stream:
                stream.truncate(24 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, "Liberty"):
                module.package(source, output, fonts)


if __name__ == "__main__":
    unittest.main()
