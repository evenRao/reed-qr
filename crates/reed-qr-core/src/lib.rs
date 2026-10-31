#![doc = include_str!("../README.md")]

mod codec;
mod encode;
mod error;
mod frame;
mod result;

use image::{ImageFormat, ImageReader};
use std::io::Cursor;

pub use encode::{EncodeOptions, ErrorCorrection, QrImage, encode_text};
pub use error::Error;
pub use frame::{FrameView, Limits, PixelFormat};
pub use result::{Detection, Landmark, PayloadStatus};

#[derive(Clone, Debug, Default)]
pub struct Decoder {
    limits: Limits,
}

impl Decoder {
    pub fn new(limits: Limits) -> Self {
        Self { limits }
    }

    pub fn decode_frame(&mut self, frame: FrameView<'_>) -> Result<Vec<Detection>, Error> {
        codec::decode(frame.grayscale(&self.limits)?, frame.width, frame.height)
    }

    pub fn decode_image(&mut self, encoded: &[u8]) -> Result<Vec<Detection>, Error> {
        if encoded.len() > self.limits.max_image_bytes {
            return Err(Error::ResourceLimit(
                "compressed image exceeds byte limit".into(),
            ));
        }
        let format = image::guess_format(encoded).map_err(|e| Error::ImageDecode(e.to_string()))?;
        if !matches!(format, ImageFormat::Png | ImageFormat::Jpeg) {
            return Err(Error::UnsupportedFormat(
                "only PNG and JPEG are enabled".into(),
            ));
        }
        let (width, height) = ImageReader::with_format(Cursor::new(encoded), format)
            .into_dimensions()
            .map_err(|e| Error::ImageDecode(e.to_string()))?;
        self.limits.check_dimensions(width, height)?;
        let mut reader = ImageReader::with_format(Cursor::new(encoded), format);
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(self.limits.max_dimension);
        limits.max_image_height = Some(self.limits.max_dimension);
        limits.max_alloc = Some(128 * 1024 * 1024);
        reader.limits(limits);
        let gray = reader
            .decode()
            .map_err(|e| Error::ImageDecode(e.to_string()))?
            .into_luma8();
        codec::decode(gray.into_raw(), width, height)
    }
}
