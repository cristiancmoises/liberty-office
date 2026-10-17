#!/usr/bin/env bash
# GridCraft MIT OR Apache-2.0 build; run inside the exact pinned Rust image.
set -euo pipefail
readonly BUILD_IMAGE='rust:1.95.0-bookworm@sha256:6258907abe69656e41cd992e0b705cdcfabcbbe3db374f92ed2d47121282d4a1'
readonly SOURCE_COMMIT='d9d09f0baa912e88c5111107903fc8c640214b57'
readonly SOURCE_SHA='3f4fc387e910a3a4c6e435f33b9b123abb6d3347399d589f9b791a9f53c50b25'
readonly BINDGEN_SHA='82d12bb940e2d4e72e0d5605387fc1b8ca179044e012b620f0ce4e7440e8320e'
readonly BINDGEN_NAME='wasm-bindgen-0.2.129-x86_64-unknown-linux-musl'
readonly FONTS_COMMIT='abb83316d96aa59c1cf64784289e378fe9fa5695'
readonly FONTS_SHA='53e41ed01ee81a0ef664601a73fb87281f1fd748e724f560c8128d7d33eb3328'
readonly BINARYEN_SHA='2dc9c7813f5375db93d96ead4b78222fcc3e2677bbb832297af4797782a37489'
readonly REPOSITORY="$(cd "$(dirname "$0")/.." && pwd)"
readonly WORK="${1:?usage: build_gridcraft_web.sh ABSOLUTE_WORK ABSOLUTE_OUTPUT}"
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
fetch_verified "https://codeload.github.com/storytold/gridcraft/tar.gz/$SOURCE_COMMIT" "$WORK/source.tar.gz" "$SOURCE_SHA"
fetch_verified "https://github.com/wasm-bindgen/wasm-bindgen/releases/download/0.2.129/$BINDGEN_NAME.tar.gz" "$WORK/bindgen.tar.gz" "$BINDGEN_SHA"
fetch_verified "https://codeload.github.com/storytold/craft-fonts/tar.gz/$FONTS_COMMIT" "$WORK/fonts.tar.gz" "$FONTS_SHA"
fetch_verified 'https://github.com/WebAssembly/binaryen/releases/download/version_133/binaryen-version_133-x86_64-linux.tar.gz' "$WORK/binaryen.tar.gz" "$BINARYEN_SHA"
[[ ! -e "$WORK/source" ]] || { echo 'Use a fresh work/source directory; existing source is not overwritten.' >&2; exit 2; }
mkdir "$WORK/source"
tar -xzf "$WORK/source.tar.gz" --strip-components=1 -C "$WORK/source"
tar -xzf "$WORK/bindgen.tar.gz" -C "$WORK"
tar -xzf "$WORK/binaryen.tar.gz" -C "$WORK"
mkdir -p "$WORK/craft-fonts"
tar -xzf "$WORK/fonts.tar.gz" --strip-components=1 -C "$WORK/craft-fonts"
python3 "$REPOSITORY/scripts/patch_gridcraft_web.py" "$WORK/source"
python3 "$REPOSITORY/patches/gridcraft-web/test_package.py"
export CARGO_BUILD_JOBS=1 CARGO_HOME="$WORK/cargo" SOURCE_DATE_EPOCH=1791936000
export CRAFT_FONTS_DIR="$WORK/craft-fonts" CRAFT_FONTS_REQUIRED=1
# Use the actual pinned release profile (opt-level 3, thin LTO), as Trunk does.
export CARGO_PROFILE_RELEASE_LTO=thin
(cd "$WORK/source" && CARGO_TARGET_DIR="$WORK/native-target" CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_DEV_OPT_LEVEL=0 CARGO_PROFILE_TEST_DEBUG=0 CARGO_PROFILE_TEST_OPT_LEVEL=0 cargo test --locked -p liberty-gridcraft-input-tests -- --test-threads=1)
disk_floor
rustup target add wasm32-unknown-unknown
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$WORK/target}"
export RUSTFLAGS="--remap-path-prefix=$WORK/source=/gridcraft"
(cd "$WORK/source" && cargo build --locked -p gridcraft-web --target wasm32-unknown-unknown --release)
disk_floor
"$WORK/$BINDGEN_NAME/wasm-bindgen" --target web --weak-refs --out-name gridcraft-web --out-dir "$OUTPUT" "$CARGO_TARGET_DIR/wasm32-unknown-unknown/release/gridcraft-web.wasm"
BINARYEN_CORES=1 "$WORK/binaryen-version_133/bin/wasm-opt" -Oz --enable-bulk-memory --enable-bulk-memory-opt --enable-nontrapping-float-to-int --enable-sign-ext --enable-reference-types --enable-multivalue "$OUTPUT/gridcraft-web_bg.wasm" -o "$OUTPUT/gridcraft-web_bg.wasm.optimized"
mv "$OUTPUT/gridcraft-web_bg.wasm.optimized" "$OUTPUT/gridcraft-web_bg.wasm"
python3 "$REPOSITORY/scripts/package_gridcraft_web.py" "$WORK/source" "$OUTPUT" "$WORK/craft-fonts"
