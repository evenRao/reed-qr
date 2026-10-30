#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("invalid frame: {0}")]
    InvalidFrame(String),
    #[error("unsupported format: {0}")]
    UnsupportedFormat(String),
    #[error("resource limit: {0}")]
    ResourceLimit(String),
    #[error("image decoding failed: {0}")]
    ImageDecode(String),
    #[error("QR encoding failed: {0}")]
    Encode(String),
    #[error("QR codec failed: {0}")]
    Codec(String),
}
