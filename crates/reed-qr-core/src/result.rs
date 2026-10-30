#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PayloadStatus {
    ExactBytes,
    TextOnly,
    Unsupported,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Landmark {
    pub x: f32,
    pub y: f32,
    /// Finder-pattern or alignment-pattern center, never an outer corner.
    pub kind: &'static str,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Detection {
    pub format: &'static str,
    pub payload_bytes: Option<Vec<u8>>,
    pub text: Option<String>,
    pub payload_status: PayloadStatus,
    /// Original byte segments, preserved even when the complete payload is unsupported.
    pub byte_segments: Vec<Vec<u8>>,
    pub landmarks: Vec<Landmark>,
    pub corners: Option<[(f32, f32); 4]>,
}
