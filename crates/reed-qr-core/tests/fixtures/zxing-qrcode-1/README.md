These are unmodified `2.png`, `10.png`, `12.png`, and `16.png` from
[ZXing 3.5.3's QR black-box corpus](https://github.com/zxing/zxing/tree/zxing-3.5.3/core/src/test/resources/blackbox/qrcode-1).
They were copied from `corpus.zip` inside the evidence archive attached to
[issue #2](https://github.com/evenRao/reed-qr/issues/2) and verified against the archive checksums.

The original images preserve the QR segment layout. The Rust contract test uses
the matching upstream labels, with the literal backslash and CRLF line endings
represented explicitly, and expects complete text and partial byte segments.

The fixtures are distributed under Apache-2.0. The upstream LICENSE and NOTICE
are included here.
