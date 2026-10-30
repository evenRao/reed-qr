use std::io::Cursor;

use image::{DynamicImage, GrayImage, ImageFormat};
use rxing::{BarcodeFormat, EncodeHints, Writer, qrcode::QRCodeWriter};

use crate::{Error, FrameView, PixelFormat};

#[derive(Clone, Copy, Debug, Default)]
pub enum ErrorCorrection {
    L,
    #[default]
    M,
    Q,
    H,
}

#[derive(Clone, Debug)]
pub struct EncodeOptions {
    pub error_correction: ErrorCorrection,
    pub pixels_per_module: u32,
    pub quiet_zone: u32,
    pub max_dimension: u32,
}

impl Default for EncodeOptions {
    fn default() -> Self {
        Self {
            error_correction: ErrorCorrection::M,
            pixels_per_module: 8,
            quiet_zone: 4,
            max_dimension: 4096,
        }
    }
}

#[derive(Clone, Debug)]
pub struct QrImage {
    width: u32,
    pixels: Vec<u8>,
}

impl QrImage {
    pub fn width(&self) -> u32 {
        self.width
    }
    pub fn height(&self) -> u32 {
        self.width
    }
    pub fn gray8(&self) -> &[u8] {
        &self.pixels
    }
    pub fn as_frame(&self) -> FrameView<'_> {
        FrameView {
            data: &self.pixels,
            width: self.width,
            height: self.width,
            row_stride: self.width as usize,
            format: PixelFormat::Gray8,
        }
    }
    pub fn to_png(&self) -> Result<Vec<u8>, Error> {
        let image = GrayImage::from_raw(self.width, self.width, self.pixels.clone())
            .ok_or_else(|| Error::Encode("invalid rendered image".into()))?;
        let mut output = Cursor::new(Vec::new());
        DynamicImage::ImageLuma8(image)
            .write_to(&mut output, ImageFormat::Png)
            .map_err(|e| Error::Encode(e.to_string()))?;
        Ok(output.into_inner())
    }
}

pub fn encode_text(text: &str, options: &EncodeOptions) -> Result<QrImage, Error> {
    if text.is_empty() || text.len() > 16 * 1024 {
        return Err(Error::Encode(
            "text must contain 1 to 16384 UTF-8 bytes; QR capacity may be lower".into(),
        ));
    }
    if options.pixels_per_module == 0 || !(4..=64).contains(&options.quiet_zone) {
        return Err(Error::Encode(
            "scale must be positive and quiet zone must be 4 to 64 modules".into(),
        ));
    }
    let hints = EncodeHints {
        ErrorCorrection: Some(format!("{:?}", options.error_correction)),
        CharacterSet: Some("UTF-8".into()),
        Margin: Some(options.quiet_zone.to_string()),
        ..Default::default()
    };
    // Request the smallest module grid, including the quiet zone, then scale ourselves.
    let matrix = QRCodeWriter
        .encode_with_hints(text, &BarcodeFormat::QR_CODE, 0, 0, &hints)
        .map_err(|e| Error::Encode(e.to_string()))?;
    let width = matrix
        .getWidth()
        .checked_mul(options.pixels_per_module)
        .ok_or_else(|| Error::ResourceLimit("rendered dimension overflow".into()))?;
    if width > options.max_dimension.min(4096) {
        return Err(Error::ResourceLimit(
            "rendered image exceeds dimension limit (hard ceiling 4096)".into(),
        ));
    }
    let mut pixels = Vec::with_capacity(width as usize * width as usize);
    for y in 0..width {
        for x in 0..width {
            pixels.push(
                if matrix.get(x / options.pixels_per_module, y / options.pixels_per_module) {
                    0
                } else {
                    255
                },
            );
        }
    }
    Ok(QrImage { width, pixels })
}
