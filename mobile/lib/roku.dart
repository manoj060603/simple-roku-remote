import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:xml/xml.dart';

class RokuException implements Exception {
  const RokuException(this.message);
  final String message;
  @override
  String toString() => message;
}

String validateTvAddress(String value) {
  final text = value.trim();
  if (!RegExp(r'^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$').hasMatch(text)) {
    throw const RokuException('Enter the TV’s IPv4 address, such as 192.168.1.50.');
  }
  final parts = text.split('.').map(int.parse).toList();
  if (parts.any((n) => n > 255) ||
      parts.map((n) => n.toString()).join('.') != text ||
      !(parts[0] == 10 ||
          (parts[0] == 172 && parts[1] >= 16 && parts[1] <= 31) ||
          (parts[0] == 192 && parts[1] == 168))) {
    throw const RokuException('Use the TV’s private Wi-Fi address from Settings → Network → About.');
  }
  return text;
}

abstract interface class RokuTransport {
  Future<String> send(String method, Uri uri, {Duration? timeout});
  void close();
}

class NativeRokuTransport implements RokuTransport {
  NativeRokuTransport() : _http = HttpClient() {
    _http.connectionTimeout = const Duration(seconds: 4);
  }
  final HttpClient _http;

  @override
  Future<String> send(String method, Uri uri, {Duration? timeout}) async {
    HttpClientRequest? request;
    final limit = timeout ?? const Duration(seconds: 6);
    try {
      return await (() async {
        request = await _http.openUrl(method, uri);
        request!.followRedirects = false;
        if (method == 'POST') request!.contentLength = 0;
        final response = await request!.close();
        if (response.statusCode != 200) {
          throw RokuException(response.statusCode == 403
              ? 'Enable Control by mobile apps in the TV’s advanced system settings.'
              : 'The TV rejected the command (${response.statusCode}). Check Control by mobile apps.');
        }
        final bytes = <int>[];
        await for (final chunk in response) {
          if (bytes.length + chunk.length > 262144) {
            throw const RokuException('The TV’s response was too large.');
          }
          bytes.addAll(chunk);
        }
        return utf8.decode(bytes);
      })().timeout(limit);
    } on TimeoutException {
      request?.abort();
      throw const RokuException('The TV timed out. Check the TV before repeating a command.');
    } on SocketException {
      throw const RokuException('Cannot reach the TV. Use the same Wi-Fi and allow Local Network access on your phone.');
    } on HttpException {
      throw const RokuException('The TV connection closed. Check Wi-Fi and try again.');
    } on FormatException {
      throw const RokuException('The TV returned an unreadable response.');
    }
  }

  @override
  void close() => _http.close(force: true);
}

class TvInfo {
  const TvInfo({required this.model, required this.name, required this.power, required this.isTv});
  final String model;
  final String name;
  final String power;
  final bool isTv;
  bool get isOn => power == 'PowerOn';
  bool get isStandby => const {'Ready', 'Standby', 'PowerOff'}.contains(power);
  TvInfo withPower(String value) => TvInfo(model: model, name: name, power: value, isTv: isTv);
}

class TvApp {
  const TvApp(this.id, this.name);
  final String id;
  final String name;
}

class RokuClient {
  RokuClient(String address, {RokuTransport? transport})
      : host = validateTvAddress(address), _transport = transport ?? NativeRokuTransport();
  final String host;
  final RokuTransport _transport;
  bool _closed = false;
  List<TvApp> _apps = const [];

  static const keys = {
    'Home', 'Back', 'Up', 'Down', 'Left', 'Right', 'Select', 'Play',
    'Rev', 'Fwd', 'InstantReplay', 'Info', 'VolumeUp', 'VolumeDown',
    'VolumeMute', 'PowerOn', 'PowerOff', 'InputHDMI1', 'InputHDMI2',
    'InputHDMI3', 'Backspace',
  };

  Uri endpoint(List<String> segments) =>
      Uri(scheme: 'http', host: host, port: 8060, pathSegments: segments);

  Future<String> _request(String method, List<String> path, {Duration? timeout}) {
    if (_closed) throw const RokuException('Connection changed. Please try again.');
    return _transport.send(method, endpoint(path), timeout: timeout);
  }

  XmlElement _xml(String value, String expected) {
    try {
      final root = XmlDocument.parse(value).rootElement;
      if (root.name.local != expected) throw const FormatException();
      return root;
    } catch (_) {
      throw const RokuException('This address did not return a valid Roku response.');
    }
  }

  Future<TvInfo> deviceInfo() async {
    final root = _xml(await _request('GET', ['query', 'device-info']), 'device-info');
    String field(String name) => root.getElement(name)?.innerText.trim() ?? '';
    final model = field('model-name');
    if (model.isEmpty) throw const RokuException('No Roku TV was found at that address.');
    final friendly = field('friendly-device-name');
    final userName = field('user-device-name');
    return TvInfo(
      model: model,
      name: friendly.isNotEmpty ? friendly : (userName.isNotEmpty ? userName : 'Your Roku'),
      power: field('power-mode'),
      isTv: field('is-tv') == 'true',
    );
  }

  Future<List<TvApp>> apps() async {
    final root = _xml(await _request('GET', ['query', 'apps']), 'apps');
    final validId = RegExp(r'^[A-Za-z0-9._-]{1,80}$');
    _apps = root.findElements('app')
        .where((item) => item.getAttribute('type') != 'tvin' && validId.hasMatch(item.getAttribute('id') ?? ''))
        .map((item) => TvApp(item.getAttribute('id')!, item.innerText.trim().isEmpty ? 'App' : item.innerText.trim()))
        .toList(growable: false);
    return List.unmodifiable(_apps);
  }

  Future<void> key(String value) async {
    if (!keys.contains(value)) throw const RokuException('That button is not supported.');
    await _request('POST', ['keypress', value]);
  }

  Future<void> launch(String id) async {
    if (!_apps.any((app) => app.id == id)) throw const RokuException('Choose an installed TV app.');
    await _request('POST', ['launch', id]);
  }

  Future<int> sendText(String text) async {
    final chars = text.runes.toList(growable: false);
    if (chars.isEmpty || chars.length > 80 || chars.any((c) => c < 32 || c == 127)) {
      throw const RokuException('Enter 1–80 characters on one line.');
    }
    final watch = Stopwatch()..start();
    var sent = 0;
    for (final char in chars) {
      final remaining = const Duration(seconds: 10) - watch.elapsed;
      if (remaining <= Duration.zero) {
        throw RokuException('Stopped after $sent characters. Check the TV before sending again.');
      }
      try {
        await _request('POST', ['keypress', 'Lit_${String.fromCharCode(char)}'],
            timeout: remaining < const Duration(seconds: 6) ? remaining : const Duration(seconds: 6));
      } catch (_) {
        throw RokuException('Stopped after $sent characters. Check the TV before sending again.');
      }
      sent++;
    }
    return sent;
  }

  void close() {
    _closed = true;
    _transport.close();
  }
}
