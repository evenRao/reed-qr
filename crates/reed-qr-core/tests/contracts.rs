use image::{GrayImage, ImageFormat};
use qrcode::{Color, EcLevel, QrCode, Version, bits::Bits};
use reed_qr_core::{
    Decoder, EncodeOptions, Error, FrameView, Limits, PayloadStatus, PixelFormat, encode_text,
};

fn independent_qr(payload: &[u8], byte_mode: bool) -> GrayImage {
    let code = if byte_mode {
        let mut bits = Bits::new(Version::Normal(3));
        bits.push_byte_data(payload).unwrap();
        bits.push_terminator(EcLevel::M).unwrap();
        QrCode::with_bits(bits, EcLevel::M).unwrap()
    } else {
        QrCode::new(payload).unwrap()
    };
    let modules = code.width();
    let scale = 6;
    let side = (modules + 8) * scale;
    GrayImage::from_fn(side as u32, side as u32, |x, y| {
        let mx = x as usize / scale;
        let my = y as usize / scale;
        let dark = mx >= 4
            && my >= 4
            && mx < modules + 4
            && my < modules + 4
            && code[(mx - 4, my - 4)] == Color::Dark;
        image::Luma([if dark { 0 } else { 255 }])
    })
}

fn decode(image: &GrayImage) -> Vec<reed_qr_core::Detection> {
    Decoder::default()
        .decode_frame(FrameView {
            data: image.as_raw(),
            width: image.width(),
            height: image.height(),
            row_stride: image.width() as usize,
            format: PixelFormat::Gray8,
        })
        .unwrap()
}

#[test]
fn independently_generated_text_and_rotations() {
    for text in ["1234567890", "REED QR 2026", "Hello, 世界 🦀"] {
        let mut image = independent_qr(text.as_bytes(), false);
        for _ in 0..4 {
            let results = decode(&image);
            assert_eq!(results.len(), 1, "payload {text}");
            assert_eq!(results[0].text.as_deref(), Some(text));
            assert!(results[0].corners.is_none());
            assert!(results[0].landmarks.iter().all(|p| p.x >= 0.0
                && p.x < image.width() as f32
                && p.y >= 0.0
                && p.y < image.height() as f32));
            image = image::imageops::rotate90(&image);
        }
    }
}

#[test]
fn arbitrary_binary_byte_mode_preserves_exact_bytes_without_fake_text() {
    let binary = b"\x00\xff\x80\xc0\xafREED\x00\xfe";
    let result = decode(&independent_qr(binary, true)).remove(0);
    assert_eq!(result.payload_bytes.as_deref(), Some(binary.as_slice()));
    assert_eq!(result.byte_segments, vec![binary.to_vec()]);
    assert_eq!(result.payload_status, PayloadStatus::ExactBytes);
    assert!(result.text.is_none());
}

#[test]
fn byte_mode_unicode_and_embedded_nul_are_faithful() {
    let text = "item\0世界";
    let result = decode(&independent_qr(text.as_bytes(), true)).remove(0);
    assert_eq!(result.payload_bytes.as_deref(), Some(text.as_bytes()));
    assert_eq!(result.text.as_deref(), Some(text));
}

#[test]
fn mixed_modes_do_not_mislabel_byte_segments_as_the_whole_payload() {
    let mut bits = Bits::new(Version::Normal(3));
    bits.push_numeric_data(b"12345").unwrap();
    bits.push_byte_data(b"hello").unwrap();
    bits.push_terminator(EcLevel::M).unwrap();
    let code = QrCode::with_bits(bits, EcLevel::M).unwrap();
    let modules = code.width();
    let image = GrayImage::from_fn(
        ((modules + 8) * 6) as u32,
        ((modules + 8) * 6) as u32,
        |x, y| {
            let (x, y) = (x as usize / 6, y as usize / 6);
            image::Luma([
                if x >= 4
                    && y >= 4
                    && x < modules + 4
                    && y < modules + 4
                    && code[(x - 4, y - 4)] == Color::Dark
                {
                    0
                } else {
                    255
                },
            ])
        },
    );
    let result = decode(&image).remove(0);
    assert_eq!(result.byte_segments, vec![b"hello".to_vec()]);
    assert!(result.payload_bytes.is_none());
    assert_eq!(result.payload_status, PayloadStatus::Unsupported);
}

#[test]
fn multiple_distinct_symbols_in_one_frame() {
    let left = independent_qr(b"ITEM-ONE", false);
    let right = independent_qr(b"ITEM-TWO", false);
    let mut canvas = GrayImage::from_pixel(
        left.width() + right.width() + 60,
        left.height().max(right.height()) + 40,
        image::Luma([255]),
    );
    image::imageops::replace(&mut canvas, &left, 0, 20);
    image::imageops::replace(&mut canvas, &right, i64::from(left.width() + 60), 20);
    let mut texts: Vec<_> = decode(&canvas).into_iter().filter_map(|r| r.text).collect();
    texts.sort();
    assert_eq!(texts, ["ITEM-ONE", "ITEM-TWO"]);
}

#[test]
fn packed_pixel_formats_honor_row_padding() {
    let image = independent_qr(b"PADDED FRAME", false);
    for format in [
        PixelFormat::Gray8,
        PixelFormat::Rgb24,
        PixelFormat::Rgba8,
        PixelFormat::Bgra8,
    ] {
        let bpp = format.bytes_per_pixel();
        let stride = image.width() as usize * bpp + 7;
        let mut buffer = vec![17; stride * image.height() as usize];
        for y in 0..image.height() as usize {
            for x in 0..image.width() as usize {
                let value = image.get_pixel(x as u32, y as u32)[0];
                buffer[y * stride + x * bpp..y * stride + x * bpp + bpp].fill(value);
                if bpp == 4 {
                    buffer[y * stride + x * bpp + 3] = 255;
                }
            }
        }
        let result = Decoder::default()
            .decode_frame(FrameView {
                data: &buffer,
                width: image.width(),
                height: image.height(),
                row_stride: stride,
                format,
            })
            .unwrap();
        assert_eq!(result[0].text.as_deref(), Some("PADDED FRAME"));
    }
}

#[test]
fn blank_frame_is_an_ordinary_miss() {
    assert!(decode(&GrayImage::from_pixel(128, 128, image::Luma([255]))).is_empty());
}

#[test]
fn malformed_layouts_and_overflow_are_errors() {
    for (width, height, stride, length) in [
        (0, 4, 4, 16),
        (4, 0, 4, 16),
        (4, 4, 3, 16),
        (4, 4, 4, 15),
        (4, 4, usize::MAX, 16),
    ] {
        let data = vec![255; length];
        let result = Decoder::default().decode_frame(FrameView {
            data: &data,
            width,
            height,
            row_stride: stride,
            format: PixelFormat::Gray8,
        });
        assert!(matches!(result, Err(Error::InvalidFrame(_))));
    }
    assert!(matches!(
        Decoder::default().decode_frame(FrameView {
            data: &[],
            width: u32::MAX,
            height: u32::MAX,
            row_stride: usize::MAX,
            format: PixelFormat::Rgba8,
        }),
        Err(Error::ResourceLimit(_))
    ));
}

#[test]
fn png_and_jpeg_loading_and_dimension_limits() {
    let generated = encode_text("Hello, 世界 🦀", &EncodeOptions::default()).unwrap();
    let png = generated.to_png().unwrap();
    assert_eq!(
        Decoder::default().decode_image(&png).unwrap()[0]
            .text
            .as_deref(),
        Some("Hello, 世界 🦀")
    );
    let image = independent_qr(b"JPEG INPUT", false);
    let mut encoded = std::io::Cursor::new(Vec::new());
    image::DynamicImage::ImageLuma8(image)
        .write_to(&mut encoded, ImageFormat::Jpeg)
        .unwrap();
    assert_eq!(
        Decoder::default().decode_image(encoded.get_ref()).unwrap()[0]
            .text
            .as_deref(),
        Some("JPEG INPUT")
    );
    let limits = Limits {
        max_pixels: 4,
        ..Limits::default()
    };
    assert!(matches!(
        Decoder::new(limits).decode_image(&png),
        Err(Error::ResourceLimit(_))
    ));
    assert!(matches!(
        Decoder::default().decode_image(b"not an image"),
        Err(Error::ImageDecode(_))
    ));
    assert!(matches!(
        Decoder::default().decode_image(b"GIF89a"),
        Err(Error::UnsupportedFormat(_))
    ));
}

#[test]
fn generation_preserves_quiet_zone_and_rejects_bad_settings() {
    let options = EncodeOptions::default();
    let image = encode_text("REED QR", &options).unwrap();
    let quiet = options.quiet_zone * options.pixels_per_module;
    for y in 0..quiet {
        assert!(
            image.gray8()
                [y as usize * image.width() as usize..(y as usize + 1) * image.width() as usize]
                .iter()
                .all(|p| *p == 255)
        );
    }
    assert!(matches!(encode_text("", &options), Err(Error::Encode(_))));
    assert!(matches!(
        encode_text(
            "REED",
            &EncodeOptions {
                pixels_per_module: 0,
                ..options.clone()
            }
        ),
        Err(Error::Encode(_))
    ));
    assert!(matches!(
        encode_text(
            "REED",
            &EncodeOptions {
                quiet_zone: 3,
                ..options.clone()
            }
        ),
        Err(Error::Encode(_))
    ));
    assert!(matches!(
        encode_text(
            "REED",
            &EncodeOptions {
                pixels_per_module: u32::MAX,
                ..options
            }
        ),
        Err(Error::ResourceLimit(_))
    ));
}
