use rxing::{
    BinaryBitmap, DecodeHints, Exceptions, Luma8LuminanceSource,
    common::{BitSource, DetectorRXingResult, Eci, HybridBinarizer},
    multi::qrcode::detector::MultiDetector,
    qrcode::{
        common::{Mode, Version},
        decoder::{QRCodeDecoderMetaData, qrcode_decoder},
    },
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
        let backend_text = decoded.getText();
        let (payload_bytes, text) = if decoded.hasStructuredAppend() {
            (None, None)
        } else if segments.is_empty() {
            (None, Some(backend_text.to_owned()))
        } else {
            match verify_payload(decoded.getRawBytes(), version, &segments) {
                Some(VerifiedPayload::ExactBytes) => {
                    let bytes = segments.concat();
                    let text = std::str::from_utf8(&bytes)
                        .ok()
                        .filter(|text| *text == backend_text)
                        .map(str::to_owned);
                    (Some(bytes), text)
                }
                Some(VerifiedPayload::MixedText { utf8_len }) if backend_text.len() == utf8_len => {
                    (None, Some(backend_text.to_owned()))
                }
                _ => (None, None),
            }
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

enum VerifiedPayload {
    ExactBytes,
    MixedText { utf8_len: usize },
}

// Verify the modes and byte segments in rxing's corrected codewords.
// rxing remains responsible for decoding and combining the text.
fn verify_payload(raw: &[u8], version: u32, segments: &[Vec<u8>]) -> Option<VerifiedPayload> {
    let version = Version::getVersionForNumber(version).ok()?;
    let mut bits = BitSource::new(raw);
    let mut index = 0;
    let mut eci = None;
    let mut has_non_byte_mode = false;
    let mut byte_text_is_reliable = true;
    let mut utf8_len = 0;

    while bits.available() >= 4 {
        let mode = Mode::forBits(bits.readBits(4).ok()? as u8).ok()?;
        match mode {
            Mode::TERMINATOR => break,
            Mode::ECI => {
                let first = bits.readBits(8).ok()?;
                eci = Some(match first {
                    0..=127 => first,
                    128..=191 => ((first & 0x3f) << 8) | bits.readBits(8).ok()?,
                    192..=223 => ((first & 0x1f) << 16) | bits.readBits(16).ok()?,
                    _ => return None,
                });
            }
            Mode::BYTE => {
                let length = bits
                    .readBits(mode.getCharacterCountBits(version).into())
                    .ok()? as usize;
                let segment = segments.get(index)?;
                if length != segment.len() {
                    return None;
                }
                for byte in segment {
                    if bits.readBits(8).ok()? != u32::from(*byte) {
                        return None;
                    }
                }
                // Without a charset declaration, accept only unambiguous ASCII.
                byte_text_is_reliable &= match eci {
                    None => segment.is_ascii(),
                    Some(assignment) if assignment == Eci::UTF8 as u32 => {
                        std::str::from_utf8(segment).is_ok()
                    }
                    Some(_) => false,
                };
                utf8_len += length;
                index += 1;
            }
            Mode::NUMERIC | Mode::ALPHANUMERIC => {
                let count = bits
                    .readBits(mode.getCharacterCountBits(version).into())
                    .ok()? as usize;
                let mut remaining = if mode == Mode::NUMERIC {
                    (count / 3) * 10 + [0, 4, 7][count % 3]
                } else {
                    (count / 2) * 11 + (count % 2) * 6
                };
                while remaining > 0 {
                    let step = remaining.min(32);
                    bits.readBits(step).ok()?;
                    remaining -= step;
                }
                has_non_byte_mode = true;
                utf8_len += count;
            }
            _ => return None,
        }
    }

    if index == 0 || index != segments.len() {
        return None;
    }
    if !has_non_byte_mode {
        Some(VerifiedPayload::ExactBytes)
    } else if byte_text_is_reliable {
        Some(VerifiedPayload::MixedText { utf8_len })
    } else {
        None
    }
}
