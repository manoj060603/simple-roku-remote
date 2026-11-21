# Android 0.2.0 verification

- Build source: 1e09d2a57b176546badd885c6aef784b9f6bb97f
- Package: io.github.manoj060603.simplerokuremote
- Version: 0.2.0 (build 2)
- APK size: 52,453,482 bytes
- APK SHA-256: 09b05aa77d03293d5e925007d61a0a7b16ecd8cbcf4cc8a8228da6e6ecd618ed
- Signing certificate SHA-256: 928f747ec460f960b82cbbadea091ab7cbfa98accacd4c9e18b04278f9b364be
- Signature: Android APK Signature Scheme v2 verified successfully; RSA 3072-bit personal signing identity.
- Architectures: arm64-v8a, armeabi-v7a, x86_64.
- Compile/target SDK: 36.
- Build worker: Virginia Tech ARC, Linux x86_64.
- Toolchain: Flutter 3.47.9 / Dart 3.13.7; full Temurin JDK 17.0.21.1+2.

All 20 shared client/controller/widget checks passed. Checks include private-address validation, direct ECP URLs, permitted commands and app IDs, Unicode encoding, text failure progress, request size and timeout behavior, redirect rejection, wake ordering, queue bounds, changing TVs, saved-address restore, phone text entry, and small-screen layouts.

The actual release APK was inspected with Android build tools. Its signing verification succeeded, its package/version metadata matched the source, and its normal network permission is INTERNET. The only additional declared permission is an app-specific signature permission for non-exported receivers.

No physical Android-phone test against a TV has been performed yet. Unit, HTTP, and UI tests use fake TVs. The previously verified laptop-controller session is separate from this native app.

The private Android signing key remains on the build worker and is not included in the public repository or release.
