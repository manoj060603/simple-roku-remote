# Standalone Roku remote for Android and iPhone

One Flutter codebase connects directly from the phone to the Roku's ECP service on the local network. The laptop, Python controller, ARC, and GitHub are not involved while using the installed app.

## Connect

1. Install the phone app and connect the phone to the TV's Wi-Fi.
2. Enter the TV's IPv4 address from Settings > Network > About.
3. Allow Local Network access if iPhone asks, then connect.
4. Use Turn TV on, navigation, volume, playback, app shortcuts, and HDMI inputs on supported TVs.
5. For typing, first focus a search/text field on the TV, then enter words in Type on TV and tap Send. The Keyboard tab has Delete and Press OK on TV.

The TV address is saved only in the phone's app preferences. There is no laptop pairing code, account, cloud relay, or ongoing ARC service. Each phone can install the same app and connect independently. The app is generic for Roku TVs/players, not for unrelated TV operating systems.

Power-on requires the TV to remain plugged in and connected to the network; network wake support depends on the device and power settings. Text input depends on the foreground TV app. It cannot speed up Roku OS or streaming apps.

## Build on a remote worker

Pinned SDK: Flutter 3.47.9 / Dart 3.13.7. Sources are under lib/; tests use fake TVs plus local HTTP servers. tool/prepare.py generates official Android and iOS platform templates and applies tracked network configuration and icons.

    python3 mobile/tool/install_flutter.py /path/to/worker/sdk
    python3 mobile/tool/prepare.py /path/to/worker/app --flutter /path/to/worker/sdk/flutter/bin/flutter
    cd /path/to/worker/app
    /path/to/worker/sdk/flutter/bin/flutter pub get
    /path/to/worker/sdk/flutter/bin/flutter test
    /path/to/worker/sdk/flutter/bin/flutter build apk --release

Android needs JDK 17+, Android SDK 36/build tools, and the Flutter-required NDK. The app targets Android SDK 36; per Android's documented compatibility behavior, INTERNET provides local network access at that target. No location, camera, microphone, contacts, or storage permissions are requested. Cleartext HTTP is enabled within this app because Roku ECP uses HTTP. The client restricts destinations to canonical RFC1918 IPv4 addresses and port 8060 and does not follow redirects.

For a stable personal Android signing identity, set ROKU_KEYSTORE and ROKU_STORE_PASSWORD on the build worker. Keep that key private and preserve it for updates. Without those variables, the generated Flutter release uses the development signing identity and is not a Play Store release.

iOS compilation requires a remote macOS/Xcode worker. The GitHub workflow produces an unsigned device IPA; it **cannot be installed on an iPhone until signed and provisioned**. TestFlight/App Store distribution needs the owner's Apple Developer setup. No signing identity, Apple account, or App Store listing is created by this repository.

## Verification and limits

Tests cover direct destinations, address validation, safe Unicode text paths, bounded responses, timeouts without automatic command retries, command ordering during wake-up, queue limits, changing TVs, saved addresses, and phone layouts.

Until an installed app is used against a physical TV, protocol/unit/widget checks are not a claim of end-to-end device testing. Existing laptop-controller tests are separate.

## Privacy and license

Only a TV address is persisted on the phone. Text stays in memory until sent or cleared and is never written to preferences or logs. The app has no telemetry or advertising. TV control is unencrypted local HTTP, so use a trusted Wi-Fi network; never forward ECP to the public internet.

Independent MIT-licensed project; not affiliated with Roku.

References: [Roku ECP](https://developer.roku.com/dev/docs/external-control-api), [Flutter iOS distribution](https://docs.flutter.dev/deployment/ios), [Android local network access](https://developer.android.com/privacy-and-security/local-network-permission).
