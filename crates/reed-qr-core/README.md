# reed-qr-core

Local QR encoding and decoding for Rust applications. Supports PNG/JPEG image
bytes and packed Gray8, RGB24, RGBA8 and BGRA8 frames with explicit row stride.

```rust
use reed_qr_core::{Decoder, EncodeOptions, encode_text};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let image = encode_text("order:12345", &EncodeOptions::default())?;
    let results = Decoder::default().decode_image(&image.to_png()?)?;
    assert_eq!(results[0].text.as_deref(), Some("order:12345"));
    Ok(())
}
```

The API is experimental. Encoding accepts nonempty UTF-8 text. Verified byte-mode
symbols expose exact payload bytes; numeric/alphanumeric symbols expose text.
Mixed modes and structured append have limited complete-payload support.
Detector landmarks are returned; four outer corners are not available.

The default decoder allows 4096 pixels per dimension, 2,190,400 total pixels,
8 MiB per packed frame and 16 MiB per encoded image. Default rendered QR output
fits those limits; larger custom rendering may need explicit decoder limits.
Frame layout and allocation bounds remain enforced.

The crate uses rxing behind a private codec boundary and has no Python, transport,
agent SDK or model-provider dependency. Rust operations are synchronous.

Licensed under MIT. See `LICENSE` and `THIRD_PARTY_NOTICES.txt` for project
and dependency terms.
