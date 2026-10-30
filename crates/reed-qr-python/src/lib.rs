use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    types::{PyBytes, PyDict},
};
use reed_qr_core::{
    Decoder, Detection, EncodeOptions, Error, ErrorCorrection, FrameView, Limits, PayloadStatus,
    PixelFormat,
};

create_exception!(_native, ReedQRError, PyException);
create_exception!(_native, InvalidFrameError, ReedQRError);
create_exception!(_native, UnsupportedFormatError, ReedQRError);
create_exception!(_native, ResourceLimitError, ReedQRError);
create_exception!(_native, ImageDecodeError, ReedQRError);
create_exception!(_native, EncodeError, ReedQRError);
create_exception!(_native, CodecError, ReedQRError);

type LimitsArgs = (u32, u64, usize, usize);
type LayoutArgs = (u32, u32, usize, String);
type EncodedImage = (u32, Py<PyBytes>, Py<PyBytes>);

fn limits(args: LimitsArgs) -> Limits {
    Limits {
        max_dimension: args.0,
        max_pixels: args.1,
        max_frame_bytes: args.2,
        max_image_bytes: args.3,
    }
}

fn python_error(error: Error) -> PyErr {
    let message = error.to_string();
    match error {
        Error::InvalidFrame(_) => InvalidFrameError::new_err(message),
        Error::UnsupportedFormat(_) => UnsupportedFormatError::new_err(message),
        Error::ResourceLimit(_) => ResourceLimitError::new_err(message),
        Error::ImageDecode(_) => ImageDecodeError::new_err(message),
        Error::Encode(_) => EncodeError::new_err(message),
        Error::Codec(_) => CodecError::new_err(message),
    }
}

fn pixel_format(name: &str) -> PyResult<PixelFormat> {
    match name {
        "gray8" => Ok(PixelFormat::Gray8),
        "rgb24" => Ok(PixelFormat::Rgb24),
        "rgba8" => Ok(PixelFormat::Rgba8),
        "bgra8" => Ok(PixelFormat::Bgra8),
        _ => Err(UnsupportedFormatError::new_err(
            "unsupported packed pixel format",
        )),
    }
}

fn python_detections(py: Python<'_>, detections: Vec<Detection>) -> PyResult<Vec<Py<PyDict>>> {
    detections
        .into_iter()
        .map(|detection| {
            let result = PyDict::new(py);
            result.set_item("format", detection.format)?;
            result.set_item(
                "payload_bytes",
                detection
                    .payload_bytes
                    .as_ref()
                    .map(|bytes| PyBytes::new(py, bytes)),
            )?;
            result.set_item("text", detection.text)?;
            result.set_item(
                "payload_status",
                match detection.payload_status {
                    PayloadStatus::ExactBytes => "exact_bytes",
                    PayloadStatus::TextOnly => "text_only",
                    PayloadStatus::Unsupported => "unsupported",
                },
            )?;
            result.set_item(
                "byte_segments",
                detection
                    .byte_segments
                    .iter()
                    .map(|bytes| PyBytes::new(py, bytes))
                    .collect::<Vec<_>>(),
            )?;
            result.set_item(
                "landmarks",
                detection
                    .landmarks
                    .into_iter()
                    .map(|point| (point.x, point.y, point.kind))
                    .collect::<Vec<_>>(),
            )?;
            Ok(result.unbind())
        })
        .collect()
}

#[pyfunction]
fn decode_image(
    py: Python<'_>,
    data: &Bound<'_, PyBytes>,
    options: LimitsArgs,
) -> PyResult<Vec<Py<PyDict>>> {
    let limits = limits(options);
    if data.as_bytes().len() > limits.max_image_bytes {
        return Err(ResourceLimitError::new_err(
            "compressed image exceeds byte limit",
        ));
    }
    // Snapshot before detaching. No Python-owned view enters native CPU work.
    let data = data.as_bytes().to_vec();
    let detections = py
        .detach(move || Decoder::new(limits).decode_image(&data))
        .map_err(python_error)?;
    python_detections(py, detections)
}

#[pyfunction]
fn decode_frame(
    py: Python<'_>,
    data: &Bound<'_, PyBytes>,
    layout: LayoutArgs,
    options: LimitsArgs,
) -> PyResult<Vec<Py<PyDict>>> {
    let limits = limits(options);
    let format = pixel_format(&layout.3)?;
    let view = FrameView {
        data: data.as_bytes(),
        width: layout.0,
        height: layout.1,
        row_stride: layout.2,
        format,
    };
    view.validate(&limits).map_err(python_error)?;
    let data = data.as_bytes().to_vec();
    let detections = py
        .detach(move || {
            Decoder::new(limits).decode_frame(FrameView {
                data: &data,
                width: layout.0,
                height: layout.1,
                row_stride: layout.2,
                format,
            })
        })
        .map_err(python_error)?;
    python_detections(py, detections)
}

#[pyfunction]
fn encode_text(
    py: Python<'_>,
    text: &str,
    pixels_per_module: u32,
    quiet_zone: u32,
    error_correction: &str,
) -> PyResult<EncodedImage> {
    let error_correction = match error_correction {
        "L" => ErrorCorrection::L,
        "M" => ErrorCorrection::M,
        "Q" => ErrorCorrection::Q,
        "H" => ErrorCorrection::H,
        _ => {
            return Err(EncodeError::new_err(
                "error correction must be L, M, Q, or H",
            ));
        }
    };
    if text.len() > 16 * 1024 {
        return Err(EncodeError::new_err("text exceeds input byte limit"));
    }
    let text = text.to_owned();
    let (width, pixels, png) = py
        .detach(move || -> Result<_, Error> {
            let image = reed_qr_core::encode_text(
                &text,
                &EncodeOptions {
                    error_correction,
                    pixels_per_module,
                    quiet_zone,
                    ..Default::default()
                },
            )?;
            Ok((image.width(), image.gray8().to_vec(), image.to_png()?))
        })
        .map_err(python_error)?;
    Ok((
        width,
        PyBytes::new(py, &pixels).unbind(),
        PyBytes::new(py, &png).unbind(),
    ))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(decode_image, module)?)?;
    module.add_function(wrap_pyfunction!(decode_frame, module)?)?;
    module.add_function(wrap_pyfunction!(encode_text, module)?)?;
    let py = module.py();
    module.add("ReedQRError", py.get_type::<ReedQRError>())?;
    module.add("InvalidFrameError", py.get_type::<InvalidFrameError>())?;
    module.add(
        "UnsupportedFormatError",
        py.get_type::<UnsupportedFormatError>(),
    )?;
    module.add("ResourceLimitError", py.get_type::<ResourceLimitError>())?;
    module.add("ImageDecodeError", py.get_type::<ImageDecodeError>())?;
    module.add("EncodeError", py.get_type::<EncodeError>())?;
    module.add("CodecError", py.get_type::<CodecError>())?;
    Ok(())
}
