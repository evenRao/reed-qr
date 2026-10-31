# reed-qr-core

Local QR encoding and decoding for Rust applications. Supports PNG/JPEG image
bytes and packed Gray8, RGB24, RGBA8 and BGRA8 frames with explicit row stride.

[Source](https://github.com/evenRao/reed-qr) ·
[API reference](https://docs.rs/reed-qr-core) ·
[Issues](https://github.com/evenRao/reed-qr/issues) ·
[Python and LiveKit guide](https://github.com/evenRao/reed-qr#readme)

## 1. Add the library

Requires Rust **1.99 or newer**. The first release is being prepared; registry
commands work after `0.1.0` is published. The API reference becomes available
after publication as well.

```sh
cargo new qr-demo
cd qr-demo
cargo add reed-qr-core@0.1.0
```

For a source checkout before publication, add a path dependency instead:

```toml
[dependencies]
reed-qr-core = { path = "../reed-qr/crates/reed-qr-core" }
```

Adjust that path relative to your application's `Cargo.toml`. This is a library
dependency; `cargo install` is not the application setup step.

## 2. Encode and decode

Replace `src/main.rs` with this complete example:

```rust,no_run
use reed_qr_core::{Decoder, EncodeOptions, encode_text};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let image = encode_text("order:12345", &EncodeOptions::default())?;
    let png = image.to_png()?;
    std::fs::write("qr.png", &png)?;
    let results = Decoder::default().decode_image(&png)?;
    assert_eq!(results[0].text.as_deref(), Some("order:12345"));
    println!("{} detection(s)", results.len());
    Ok(())
}
```

Run `cargo run`. It writes `qr.png` to the current directory and prints
`1 detection(s)`. For an existing image, pass PNG/JPEG bytes read with
`std::fs::read()` to `Decoder::decode_image()`.

## 3. Decode a packed frame

```rust
use reed_qr_core::{Decoder, EncodeOptions, FrameView, PixelFormat, encode_text};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let image = encode_text("frame:001", &EncodeOptions::default())?;
    let frame = FrameView {
        data: image.gray8(),
        width: image.width(),
        height: image.height(),
        row_stride: image.width() as usize,
        format: PixelFormat::Gray8,
    };
    let detections = Decoder::default().decode_frame(frame)?;
    assert_eq!(detections[0].text.as_deref(), Some("frame:001"));
    Ok(())
}
```

Replace the generated data with your capture buffer. `FrameView` borrows the
buffer for the duration of decoding. Row stride is in bytes and includes padding;
it must cover the active row. RGB24 uses three bytes per pixel; RGBA8/BGRA8 use
four and ignore alpha. Planar YUV requires conversion first. `image.as_frame()`
is a convenience for the generated image's own Gray8 buffer.

## 4. Handle results and limits

The API is experimental. Encoding accepts nonempty UTF-8 text. Verified byte-mode
symbols expose exact payload bytes; numeric/alphanumeric symbols expose text.
Mixed modes and structured append have limited complete-payload support.
Detector landmarks are returned; four outer corners are not available.

The default decoder allows 4096 pixels per dimension, 2,190,400 total pixels,
8 MiB per packed frame and 16 MiB per encoded image. Default rendered QR output
fits those limits; larger custom rendering may need explicit decoder limits.
Frame layout and allocation bounds remain enforced.

A valid image/frame with no readable QR returns an empty vector; invalid input
returns `Error`. Process all detections rather than relying on their ordering.
Use `Decoder::new(Limits { max_pixels: 1920 * 1080, ..Limits::default() })` to
choose explicit input limits. These limits do not establish a hard process RSS
cap. Validate decoded content before using it to trigger application actions.

The crate uses rxing behind a private codec boundary and has no Python, transport,
agent SDK or model-provider dependency. Rust operations are synchronous.

Camera accuracy and latency depend on input quality and hardware; no performance
guarantee is established. See
[compatibility and validation](https://github.com/evenRao/reed-qr/blob/main/docs/compatibility.md)
and [contributor checks](https://github.com/evenRao/reed-qr/blob/main/CONTRIBUTING.md).

Licensed under MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.txt` for project
and dependency terms.
