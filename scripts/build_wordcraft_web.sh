#!/usr/bin/env bash
# WordCraft MIT OR Apache-2.0 build in the exact pinned Rust toolchain.
set -euo pipefail
readonly BUILD_IMAGE='rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1'
readonly SOURCE_COMMIT='fc41918814f62645b6746ed68e71e8c2c2e85d6f'
readonly SOURCE_SHA='ea7a64508f9df85878481f41ad961f8396be0e6a4cf0f9842844a86dc7a48fb6'
readonly FONTS_COMMIT='8dcdacd5153e64560d109541a47d806f26f048c0'
readonly FONTS_SHA='c0bfca8f4dd8c98825e598c0324c66d90609fe531b212a6c9a04f6852dc5387b'
readonly BINDGEN_NAME='wasm-bindgen-0.2.129-x86_64-unknown-linux-musl'
readonly BINDGEN_SHA='82d12bb940e2d4e72e0d5605387fc1b8ca179044e012b620f0ce4e7440e8320e'
readonly BINARYEN_SHA='2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489'
readonly ARTIFACT='wordcraft-web-8f83828293ff7c4d'
readonly REPOSITORY="$(cd "$(dirname "$0")/.." && pwd)"
readonly WORK="${1:?usage: build_wordcraft_web.sh ABSOLUTE_WORK ABSOLUTE_OUTPUT}"
readonly OUTPUT="${2:?absolute output directory required}"
[[ "$WORK" == /* && "$OUTPUT" == /* && "$WORK" != / && "$OUTPUT" != / ]] || exit 2
[[ "$(uname -m)" == x86_64 ]] || { echo 'Pinned builder supports x86_64 only.' >&2; exit 2; }
rustc --version | grep -q '^rustc 1\.95\.0 ' || { echo "Use $BUILD_IMAGE" >&2; exit 2; }
[[ -f /usr/lib/x86_64-linux-gnu/libvulkan.so.1 && -f /usr/share/vulkan/icd.d/lvp_icd.x86_64.json ]] || { echo 'Native UI qualification requires the pinned CPU Vulkan builder dependencies.' >&2; exit 2; }
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
fetch_verified "https://codeload.github.com/storytold/wordcraft/tar.gz/$SOURCE_COMMIT" "$WORK/source.tar.gz" "$SOURCE_SHA"
fetch_verified "https://codeload.github.com/storytold/craft-fonts/tar.gz/$FONTS_COMMIT" "$WORK/fonts.tar.gz" "$FONTS_SHA"
fetch_verified "https://github.com/wasm-bindgen/wasm-bindgen/releases/download/0.2.129/$BINDGEN_NAME.tar.gz" "$WORK/bindgen.tar.gz" "$BINDGEN_SHA"
fetch_verified 'https://github.com/WebAssembly/binaryen/releases/download/version_133/binaryen-version_133-x86_64-linux.tar.gz' "$WORK/binaryen.tar.gz" "$BINARYEN_SHA"
[[ ! -e "$WORK/source" ]] || { echo 'Use a fresh source directory; existing work is not overwritten.' >&2; exit 2; }
mkdir "$WORK/source" "$WORK/craft-fonts"
tar -xzf "$WORK/source.tar.gz" --strip-components=1 -C "$WORK/source"
tar -xzf "$WORK/fonts.tar.gz" --strip-components=1 -C "$WORK/craft-fonts"
tar -xzf "$WORK/bindgen.tar.gz" -C "$WORK"
tar -xzf "$WORK/binaryen.tar.gz" -C "$WORK"
python3 "$REPOSITORY/scripts/patch_wordcraft_web.py" "$WORK/source"
export CARGO_BUILD_JOBS=1 CARGO_HOME="$WORK/cargo" SOURCE_DATE_EPOCH=1791936000
export CRAFT_FONTS_DIR="$WORK/craft-fonts" CRAFT_FONTS_REQUIRED=1
(cd "$WORK/source" && WGPU_BACKEND=vulkan CARGO_TARGET_DIR="$WORK/native-target" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0 cargo test --locked -p wordcraft-ui-egui -- --test-threads=1)
disk_floor
if ! rustup target list --installed | grep -qx wasm32-unknown-unknown; then rustup target add wasm32-unknown-unknown; fi
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$WORK/target}"
export RUSTFLAGS="--remap-path-prefix=$WORK/source=/wordcraft"
(cd "$WORK/source" && cargo build --locked -p wordcraft-web --target wasm32-unknown-unknown --release)
disk_floor
"$WORK/$BINDGEN_NAME/wasm-bindgen" --target web --weak-refs --out-name "$ARTIFACT" --out-dir "$OUTPUT" "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/wordcraft-web.wasm"
BINARYEN_CORES=1 "$WORK/binaryen-version_133/bin/wasm-opt" -Oz --enable-bulk-memory --enable-bulk-memory-opt --enable-nontrapping-float-to-int --enable-sign-ext --enable-reference-types --enable-multivalue "$OUTPUT/${ARTIFACT}_bg.wasm" -o "$OUTPUT/${ARTIFACT}_bg.wasm.optimized"
mv "$OUTPUT/${ARTIFACT}_bg.wasm.optimized" "$OUTPUT/${ARTIFACT}_bg.wasm"
python3 "$REPOSITORY/scripts/package_wordcraft_web.py" "$WORK/source" "$OUTPUT" "$WORK/craft-fonts"
