import 'dart:async';
import 'package:simple_roku_remote/roku.dart';
import 'package:simple_roku_remote/preferences.dart';

class RecordedRequest {
  RecordedRequest(this.method, this.uri);
  final String method;
  final Uri uri;
}

class FakeTransport implements RokuTransport {
  final requests = <RecordedRequest>[];
  bool closed = false;
  String power = 'PowerOn';
  FutureOr<String> Function(String, Uri)? handler;
  @override
  Future<String> send(String method, Uri uri, {Duration? timeout}) async {
    if (closed) throw const RokuException('Closed');
    requests.add(RecordedRequest(method, uri));
    if (handler != null) return await handler!(method, uri);
    if (method == 'POST') {
      if (uri.path == '/keypress/PowerOn') power = 'PowerOn';
      if (uri.path == '/keypress/PowerOff') power = 'Ready';
      return '';
    }
    if (uri.path == '/query/device-info') {
      return '<device-info><model-name>Roku TV</model-name><friendly-device-name>Living room</friendly-device-name><power-mode>$power</power-mode><is-tv>true</is-tv></device-info>';
    }
    if (uri.path == '/query/apps') {
      return '<apps><app id="837" type="appl">YouTube</app><app id="12" type="appl">Netflix</app><app id="13" type="appl">Prime Video</app><app id="tvinput.hdmi1" type="tvin">HDMI 1</app></apps>';
    }
    throw const RokuException('Unexpected request');
  }
  List<String> get commands => requests.where((r) => r.method == 'POST').map((r) => r.uri.pathSegments.last).toList();
  @override
  void close() { closed = true; }
}

class MemoryTvStore implements TvStore {
  MemoryTvStore([this.value]);
  String? value;
  @override
  Future<String?> load() async => value;
  @override
  Future<void> save(String host) async { value = host; }
  @override
  Future<void> clear() async { value = null; }
}
