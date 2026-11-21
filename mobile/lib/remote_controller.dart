import 'dart:async';

import 'package:flutter/foundation.dart';

import 'roku.dart';

typedef RokuFactory = RokuClient Function(String address);

class RemoteController extends ChangeNotifier {
  RemoteController({
    RokuFactory? clientFactory,
    Future<void> Function(Duration)? delay,
  }) : _factory = clientFactory ?? ((host) => RokuClient(host)),
       _delay = delay ?? ((duration) => Future<void>.delayed(duration));
  final RokuFactory _factory;
  final Future<void> Function(Duration) _delay;
  RokuClient? _client;
  Future<void> _tail = Future<void>.value();
  int _generation = 0;
  bool _disposed = false;
  bool connecting = false;
  bool reachable = false;
  String? host;
  TvInfo? info;
  List<TvApp> apps = const [];
  String? error;
  String? activity;
  int pending = 0;

  bool get canControl => _client != null && !connecting;
  void _changed() {
    if (!_disposed) notifyListeners();
  }

  Future<bool> connect(String address) async {
    final validated = validateTvAddress(address);
    final generation = ++_generation;
    _client?.close();
    final client = _factory(validated);
    _client = client;
    host = validated;
    _tail = Future<void>.value();
    pending = 0;
    info = null;
    apps = const [];
    error = null;
    connecting = true;
    reachable = false;
    _changed();
    try {
      final found = await client.deviceInfo();
      if (_disposed || generation != _generation) return false;
      info = found;
      reachable = true;
      try {
        final installed = await client.apps();
        if (_disposed || generation != _generation) return false;
        apps = installed;
      } catch (_) {
        if (generation == _generation) error = 'Connected. App shortcuts could not load; the remote still works.';
      }
      return true;
    } catch (failure) {
      if (generation == _generation) error = _message(failure);
      return false;
    } finally {
      if (generation == _generation) {
        connecting = false;
        _changed();
      }
    }
  }

  Future<void> refresh({bool reloadApps = false}) async {
    final client = _client;
    final generation = _generation;
    if (client == null || connecting || pending > 0) return;
    try {
      final value = await client.deviceInfo();
      if (_disposed || generation != _generation) return;
      info = value;
      reachable = true;
      error = null;
      if (reloadApps) {
        final installed = await client.apps();
        if (_disposed || generation != _generation) return;
        apps = installed;
      }
    } catch (failure) {
      if (generation == _generation) {
        reachable = false;
        error = _message(failure);
      }
    }
    _changed();
  }

  String _message(Object error) => error is RokuException
      ? error.message
      : 'Could not reach the TV. Check Wi-Fi and try again.';

  Future<bool> _enqueue(
    Future<void> Function(RokuClient) action, {
    String? label,
  }) {
    final client = _client;
    if (client == null || connecting) return Future.value(false);
    if (pending >= 6) {
      error = 'Let the TV catch up for a moment.';
      _changed();
      return Future.value(false);
    }
    final generation = _generation;
    final result = Completer<bool>();
    pending++;
    _changed();
    _tail = _tail.then((_) async {
      if (_disposed || generation != _generation) {
        result.complete(false);
        return;
      }
      activity = label;
      _changed();
      try {
        await action(client);
        if (_disposed || generation != _generation) {
          result.complete(false);
          return;
        }
        error = null;
        reachable = true;
        result.complete(true);
      } catch (failure) {
        if (!_disposed && generation == _generation) error = _message(failure);
        result.complete(false);
      } finally {
        if (!_disposed && generation == _generation) {
          pending--;
          activity = null;
          _changed();
        }
      }
    });
    return result.future;
  }

  Future<bool> press(String key) => _enqueue((client) => client.key(key));
  Future<bool> launch(String id) => _enqueue((client) => client.launch(id));
  Future<bool> type(String text) => _enqueue((client) async {
    await client.sendText(text);
  }, label: 'Sending text…');

  Future<bool> turnOn() => _enqueue((client) async {
    await client.key('PowerOn');
    await _delay(const Duration(seconds: 5));
    if (_disposed || !identical(_client, client)) return;
    info = await client.deviceInfo();
  }, label: 'Waking TV… please wait a few seconds');

  Future<bool> turnOff() => _enqueue((client) async {
    await client.key('PowerOff');
    info = info?.withPower('Ready');
  });

  void disconnect() {
    _generation++;
    _client?.close();
    _client = null;
    host = null;
    info = null;
    apps = const [];
    pending = 0;
    connecting = false;
    reachable = false;
    error = null;
    activity = null;
    _tail = Future<void>.value();
    _changed();
  }

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _client?.close();
    super.dispose();
  }
}
