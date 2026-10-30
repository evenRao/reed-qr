use reed_qr_core::{Decoder, EncodeOptions, encode_text};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let text = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "Hello from REED QR".into());
    let image = encode_text(&text, &EncodeOptions::default())?;
    std::fs::write("demo-qr.png", image.to_png()?)?;
    let detections = Decoder::default().decode_frame(image.as_frame())?;
    for detection in detections {
        println!("{:?}", detection);
    }
    Ok(())
}
