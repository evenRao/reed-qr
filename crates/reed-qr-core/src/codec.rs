use rxing::{
    BinaryBitmap, DecodeHints, Exceptions, Luma8LuminanceSource,
    common::{BitSource, DetectorRXingResult, HybridBinarizer},
    multi::qrcode::detector::MultiDetector,
    qrcode::decoder::{QRCodeDecoderMetaData, qrcode_decoder},
};

use crate::{Detection, Error, Landmark, PayloadStatus};

fn is_miss(error: &Exceptions) -> bool {
    matches!(
        error,
        Exceptions::NotFoundException(_)
            | Exceptions::FormatException(_)
            | Exceptions::ChecksumException(_)
            | Exceptions::ReaderException(_)
            | Exceptions::ReedSolomonException(_)
    )
}

pub(crate) fn decode(pixels: Vec<u8>, width: u32, height: u32) -> Result<Vec<Detection>, Error> {
    let source = Luma8LuminanceSource::new(pixels, width, height)
        .map_err(|e| Error::Codec(e.to_string()))?;
    let bitmap = BinaryBitmap::new(HybridBinarizer::new(source));
    let hints = DecodeHints {
        TryHarder: Some(true),
        ..Default::default()
    };
    let candidates = match MultiDetector::new(bitmap.get_black_matrix()).detectMulti(&hints) {
        Ok(found) => found,
        Err(e) if is_miss(&e) => return Ok(Vec::new()),
        Err(e) => return Err(Error::Codec(e.to_string())),
    };
    let mut detections = Vec::new();
    for candidate in candidates {
        let bits = candidate.getBits();
        let decoded = match qrcode_decoder::decode_bitmatrix_with_hints(bits, &hints) {
            Ok(result) => result,
            Err(e) if is_miss(&e) => continue,
            Err(e) => return Err(Error::Codec(e.to_string())),
        };
        let mut points = candidate.getPoints().to_vec();
        if let Some(other) = decoded.getOther()
            && let Some(metadata) = other.downcast_ref::<QRCodeDecoderMetaData>()
        {
            metadata.applyMirroredCorrection(&mut points);
        }
        let segments = decoded.getByteSegments().clone();
        let version = (bits.getWidth() - 17) / 4;
        // A conservative gate, not a replacement decoder: trust byte segments only
        // when the backend codewords contain exclusively BYTE and ECI segments.
        let payload_bytes = if !decoded.hasStructuredAppend()
            && byte_only(decoded.getRawBytes(), version, &segments)
        {
            Some(segments.concat())
        } else {
            None
        };
        let text = if let Some(bytes) = &payload_bytes {
            std::str::from_utf8(bytes)
                .ok()
                .filter(|text| *text == decoded.getText())
                .map(str::to_owned)
        } else if segments.is_empty() && !decoded.hasStructuredAppend() {
            Some(decoded.getText().to_owned())
        } else {
            None
        };
        let status = if payload_bytes.is_some() {
            PayloadStatus::ExactBytes
        } else if text.is_some() {
            PayloadStatus::TextOnly
        } else {
            PayloadStatus::Unsupported
        };
        detections.push(Detection {
            format: "QR_CODE",
            payload_bytes,
            text,
            payload_status: status,
            byte_segments: segments,
            landmarks: points
                .iter()
                .enumerate()
                .map(|(index, point)| Landmark {
                    x: point.x,
                    y: point.y,
                    kind: match index {
                        0 => "finder_bottom_left",
                        1 => "finder_top_left",
                        2 => "finder_top_right",
                        _ => "alignment",
                    },
                })
                .collect(),
            corners: None,
        });
    }
    Ok(detections)
}

// Merely verifies the mode/length envelope of backend-decoded data against the
// backend's exact byte segments. All detection, correction and decoding is rxing.
fn byte_only(raw: &[u8], version: u32, segments: &[Vec<u8>]) -> bool {
    fn check(raw: &[u8], version: u32, segments: &[Vec<u8>]) -> Option<bool> {
        let mut bits = BitSource::new(raw);
        let mut index = 0;
        while bits.available() >= 4 {
            match bits.readBits(4).ok()? {
                0 => break,
                7 => {
                    let first = bits.readBits(8).ok()?;
                    match first {
                        0..=127 => {}
                        128..=191 => {
                            bits.readBits(8).ok()?;
                        }
                        192..=223 => {
                            bits.readBits(16).ok()?;
                        }
                        _ => return Some(false),
                    }
                }
                4 => {
                    let length = bits.readBits(if version < 10 { 8 } else { 16 }).ok()? as usize;
                    let segment = segments.get(index)?;
                    if length != segment.len() {
                        return Some(false);
                    }
                    for byte in segment {
                        if bits.readBits(8).ok()? != u32::from(*byte) {
                            return Some(false);
                        }
                    }
                    index += 1;
                }
                _ => return Some(false),
            }
        }
        Some(index > 0 && index == segments.len())
    }
    check(raw, version, segments).unwrap_or(false)
}
