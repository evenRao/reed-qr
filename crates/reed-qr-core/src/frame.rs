use crate::Error;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PixelFormat {
    Gray8,
    Rgb24,
    Rgba8,
    Bgra8,
}

impl PixelFormat {
    pub const fn bytes_per_pixel(self) -> usize {
        match self {
            Self::Gray8 => 1,
            Self::Rgb24 => 3,
            Self::Rgba8 | Self::Bgra8 => 4,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Limits {
    pub max_dimension: u32,
    pub max_pixels: u64,
    pub max_frame_bytes: usize,
    pub max_image_bytes: usize,
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_dimension: 4096,
            max_pixels: 1480 * 1480,
            max_frame_bytes: 8 * 1024 * 1024,
            max_image_bytes: 16 * 1024 * 1024,
        }
    }
}

impl Limits {
    pub fn check_dimensions(&self, width: u32, height: u32) -> Result<(), Error> {
        if width == 0 || height == 0 {
            return Err(Error::InvalidFrame("dimensions must be positive".into()));
        }
        if width > self.max_dimension
            || height > self.max_dimension
            || u64::from(width) * u64::from(height) > self.max_pixels
        {
            return Err(Error::ResourceLimit(
                "image dimensions exceed configured limits".into(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug)]
pub struct FrameView<'a> {
    pub data: &'a [u8],
    pub width: u32,
    pub height: u32,
    pub row_stride: usize,
    pub format: PixelFormat,
}

impl FrameView<'_> {
    pub fn validate(&self, limits: &Limits) -> Result<(), Error> {
        limits.check_dimensions(self.width, self.height)?;
        if self.data.len() > limits.max_frame_bytes {
            return Err(Error::ResourceLimit(
                "frame storage exceeds byte limit".into(),
            ));
        }
        let row = (self.width as usize)
            .checked_mul(self.format.bytes_per_pixel())
            .ok_or_else(|| Error::InvalidFrame("row size overflow".into()))?;
        if self.row_stride < row {
            return Err(Error::InvalidFrame(
                "row stride is smaller than an active row".into(),
            ));
        }
        let required = (self.height as usize - 1)
            .checked_mul(self.row_stride)
            .and_then(|n| n.checked_add(row))
            .ok_or_else(|| Error::InvalidFrame("buffer size overflow".into()))?;
        if self.data.len() < required {
            return Err(Error::InvalidFrame(
                "buffer does not contain all active rows".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn grayscale(&self, limits: &Limits) -> Result<Vec<u8>, Error> {
        self.validate(limits)?;
        let width = self.width as usize;
        let bpp = self.format.bytes_per_pixel();
        let mut pixels = Vec::with_capacity(width * self.height as usize);
        for y in 0..self.height as usize {
            let row = &self.data[y * self.row_stride..y * self.row_stride + width * bpp];
            for pixel in row.chunks_exact(bpp) {
                let gray = match self.format {
                    PixelFormat::Gray8 => pixel[0],
                    PixelFormat::Rgb24 | PixelFormat::Rgba8 => {
                        ((77 * u32::from(pixel[0])
                            + 150 * u32::from(pixel[1])
                            + 29 * u32::from(pixel[2])
                            + 128)
                            >> 8) as u8
                    }
                    PixelFormat::Bgra8 => {
                        ((77 * u32::from(pixel[2])
                            + 150 * u32::from(pixel[1])
                            + 29 * u32::from(pixel[0])
                            + 128)
                            >> 8) as u8
                    }
                };
                pixels.push(gray);
            }
        }
        Ok(pixels)
    }
}
