#!/usr/bin/env bash
# FigCraft MIT OR Apache-2.0 browser build; run inside the pinned Rust image below.
set -euo pipefail
readonly BUILD_IMAGE='rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1'
readonly SOURCE_COMMIT='833f0d2c27f0acbae5394848930ae531fc89c724'
readonly SOURCE_SHA='f327701beaf7a025a0f124c8551472ab998d2b07baf3949c8a2d86ebcf457e59'
readonly BINDGEN_SHA='82d12bb940e2d4e72e0d5605387fc1b8ca179044e012b620f0ce4e7440e8320e'
readonly BINDGEN_NAME='wasm-bindgen-0.2.129-x86_64-unknown-linux-musl'
readonly FONTS_COMMIT='43913056ce82a3fdad0ef69f6b88d1dc922a8104'
readonly FONTS_SHA='e2dd2bb3ae39e442ee67416b9bc29b7ca8ef906e8ff2caaf5a451aaa6c662057'
readonly BINARYEN_SHA='2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489'
readonly REPOSITORY="$(cd "$(dirname "$0")/.." && pwd)"
readonly WORK="${1:?usage: build_figcraft_web.sh ABSOLUTE_WORK ABSOLUTE_OUTPUT}"
readonly OUTPUT="${2:?absolute output directory required}"
[[ "$WORK" == /* && "$OUTPUT" == /* && "$WORK" != / && "$OUTPUT" != / ]] || exit 2
[[ "$(uname -m)" == x86_64 ]] || { echo 'Pinned build tool supports x86_64 only.' >&2; exit 2; }
rustc --version | grep -q '^rustc 1\.95\.0 ' || { echo "Use $BUILD_IMAGE" >&2; exit 2; }
mkdir -p "$WORK" "$OUTPUT"
disk_floor() { [[ "$(df -Pk "$WORK" | awk 'NR==2 {print $4}')" -ge 5242880 ]] || { echo '5 GiB disk-space floor reached.' >&2; exit 1; }; }
disk_floor
fetch_verified() {
 local url="$1" destination="$2" expected="$3"
 if [[ ! -f "$destination" ]]; then
  curl --fail --location --proto '=https' --tlsv1.2 --retry 2 --output "$destination.part" "$url"
  printf '%s  %s\n' "$expected" "$destination.part" | sha256sum --check --status
  mv "$destination.part" "$destination"
 fi
 printf '%s  %s\n' "$expected" "$destination" | sha256sum --check --status
}
fetch_verified "https://github.com/storytold/figcraft/archive/$SOURCE_COMMIT.tar.gz" "$WORK/source.tar.gz" "$SOURCE_SHA"
fetch_verified "https://github.com/wasm-bindgen/wasm-bindgen/releases/download/0.2.129/$BINDGEN_NAME.tar.gz" "$WORK/bindgen.tar.gz" "$BINDGEN_SHA"
fetch_verified "https://github.com/storytold/craft-fonts/archive/$FONTS_COMMIT.tar.gz" "$WORK/fonts.tar.gz" "$FONTS_SHA"
fetch_verified 'https://github.com/WebAssembly/binaryen/releases/download/version_133/binaryen-version_133-x86_64-linux.tar.gz' "$WORK/binaryen.tar.gz" "$BINARYEN_SHA"
[[ ! -e "$WORK/source" ]] || { echo 'Use a fresh work/source directory; existing source is not overwritten.' >&2; exit 2; }
mkdir "$WORK/source"
tar -xzf "$WORK/source.tar.gz" --strip-components=1 -C "$WORK/source"
tar -xzf "$WORK/bindgen.tar.gz" -C "$WORK"
tar -xzf "$WORK/binaryen.tar.gz" -C "$WORK"
mkdir -p "$WORK/craft-fonts"
tar -xzf "$WORK/fonts.tar.gz" --strip-components=1 -C "$WORK/craft-fonts"
python3 "$REPOSITORY/scripts/patch_figcraft_web.py" "$WORK/source"
rustc --test "$REPOSITORY/patches/figcraft-web/browser_io_tests.rs" -o "$WORK/browser-io-tests"
"$WORK/browser-io-tests"
rustup target add wasm32-unknown-unknown
export CARGO_BUILD_JOBS=1 SOURCE_DATE_EPOCH=1791936000
export CARGO_HOME="$WORK/cargo"
# Upstream fat LTO exceeds the bounded builder's memory; retain size optimization
# and the original output-size gate with a deterministic thin-LTO override.
export CARGO_PROFILE_WEB_RELEASE_LTO=thin
export CRAFT_FONTS_DIR="$WORK/craft-fonts" CRAFT_FONTS_REQUIRED=1
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$WORK/target}"
export RUSTFLAGS="--remap-path-prefix=$WORK/source=/figcraft"
(cd "$WORK/source" && cargo build --locked -p figcraft-web --target wasm32-unknown-unknown --profile web-release)
disk_floor
"$WORK/$BINDGEN_NAME/wasm-bindgen" --target web --out-name figcraft-web --out-dir "$OUTPUT" "$CARGO_TARGET_DIR/wasm32-unknown-unknown/web-release/figcraft-web.wasm"
# Match the pinned upstream Trunk entrypoint's size pass and feature flags.
BINARYEN_CORES=1 "$WORK/binaryen-version_133/bin/wasm-opt" -Oz --enable-bulk-memory --enable-bulk-memory-opt --enable-nontrapping-float-to-int --enable-sign-ext --enable-reference-types --enable-multivalue "$OUTPUT/figcraft-web_bg.wasm" -o "$OUTPUT/figcraft-web_bg.wasm.optimized"
mv "$OUTPUT/figcraft-web_bg.wasm.optimized" "$OUTPUT/figcraft-web_bg.wasm"
python3 "$REPOSITORY/scripts/package_figcraft_web.py" "$WORK/source" "$OUTPUT" "$WORK/craft-fonts"
