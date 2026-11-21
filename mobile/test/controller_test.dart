import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_roku_remote/remote_controller.dart';
import 'package:simple_roku_remote/roku.dart';

import 'support/fakes.dart';

void main() {
  test('commands wait for TV wake-up and preserve their order', () async {
    final fake = FakeTransport();
    final wakeReady = Completer<void>();
    final controller = RemoteController(
      clientFactory: (host) => RokuClient(host, transport: fake),
      delay: (_) => wakeReady.future,
    );
    await controller.connect('192.168.1.50');
    final wake = controller.turnOn();
    final home = controller.press('Home');
    await Future<void>.delayed(Duration.zero);
    expect(fake.commands, ['PowerOn']);
    wakeReady.complete();
    expect(await wake, isTrue);
    expect(await home, isTrue);
    expect(fake.commands, ['PowerOn', 'Home']);
    expect(controller.pending, 0);
    controller.dispose();
  });
  test('a failed command does not break later controls', () async {
    final fake = FakeTransport();
    final controller = RemoteController(
      clientFactory: (host) => RokuClient(host, transport: fake),
    );
    await controller.connect('192.168.1.50');
    fake.handler = (_, uri) {
      if (uri.path.endsWith('/Home')) throw const RokuException('No response');
      return '';
    };
    expect(await controller.press('Home'), isFalse);
    expect(await controller.press('Up'), isTrue);
    expect(controller.error, isNull);
    controller.dispose();
  });
  test('the input queue is bounded', () async {
    final fake = FakeTransport();
    final gate = Completer<void>();
    final controller = RemoteController(
      clientFactory: (host) => RokuClient(host, transport: fake),
      delay: (_) => gate.future,
    );
    await controller.connect('192.168.1.50');
    final futures = [
      controller.turnOn(),
      for (var i = 0; i < 5; i++) controller.press('Up'),
    ];
    expect(await controller.press('Down'), isFalse);
    expect(controller.pending, 6);
    gate.complete();
    await Future.wait(futures);
    expect(fake.commands.where((c) => c == 'Down'), isEmpty);
    controller.dispose();
  });
  test('changing TVs cancels queued actions for the previous TV', () async {
    final first = FakeTransport(), second = FakeTransport();
    final gate = Completer<void>();
    final controller = RemoteController(
      clientFactory: (host) =>
          RokuClient(host, transport: host.endsWith('.50') ? first : second),
      delay: (_) => gate.future,
    );
    await controller.connect('192.168.1.50');
    final wake = controller.turnOn();
    final oldHome = controller.press('Home');
    await Future<void>.delayed(Duration.zero);
    await controller.connect('192.168.1.51');
    gate.complete();
    await wake;
    expect(await oldHome, isFalse);
    expect(first.commands, ['PowerOn']);
    expect(await controller.press('Home'), isTrue);
    expect(second.commands, ['Home']);
    expect(controller.host, '192.168.1.51');
    controller.dispose();
  });
}
