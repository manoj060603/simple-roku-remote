import 'dart:async';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:simple_roku_remote/roku.dart';

import 'support/fakes.dart';

void main() {
  test('only canonical private IPv4 addresses are accepted', () {
    for (final host in [
      '10.0.0.20',
      '172.16.0.1',
      '172.31.255.254',
      '192.168.1.50',
    ]) {
      expect(validateTvAddress(host), host);
    }
    expect(validateTvAddress(' 192.168.1.50 '), '192.168.1.50');
    for (final host in [
      '8.8.8.8',
      '127.0.0.1',
      '169.254.0.1',
      '172.15.0.1',
      '172.32.0.1',
      'localhost',
      'http://192.168.1.5',
      '192.168.1.5:8060',
      '192.168.001.5',
      '192.168.1.999',
      '::1',
    ]) {
      expect(
        () => validateTvAddress(host),
        throwsA(isA<RokuException>()),
        reason: host,
      );
    }
  });
  test('queries use the TV directly on ECP port 8060', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    final info = await client.deviceInfo();
    expect(info.model, 'Roku TV');
    expect(info.isOn, isTrue);
    expect(info.isTv, isTrue);
    expect(
      fake.requests.single.uri.toString(),
      'http://192.168.1.50:8060/query/device-info',
    );
    client.close();
  });
  test('installed apps are parsed and inputs excluded', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    final apps = await client.apps();
    expect(apps.map((a) => a.id), ['837', '12', '13']);
    await client.launch('837');
    expect(fake.commands, ['837']);
    await expectLater(client.launch('../reset'), throwsA(isA<RokuException>()));
    expect(fake.commands.length, 1);
  });
  test('only supported keys can be sent', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    await expectLater(client.key('../reset'), throwsA(isA<RokuException>()));
    expect(fake.requests, isEmpty);
    await client.key('Home');
    expect(fake.commands, ['Home']);
  });
  test(
    'text is sent once per Unicode code point with safe path encoding',
    () async {
      final fake = FakeTransport();
      final client = RokuClient('192.168.1.50', transport: fake);
      expect(await client.sendText('é/😀%?'), 5);
      expect(fake.commands, ['Lit_é', 'Lit_/', 'Lit_😀', 'Lit_%', 'Lit_?']);
      expect(fake.requests[1].uri.toString(), contains('Lit_%2F'));
      expect(fake.requests[3].uri.toString(), contains('Lit_%25'));
    },
  );
  test('invalid text is rejected before contacting the TV', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    for (final value in ['', 'a' * 81, 'one\ntwo', '\u0000']) {
      await expectLater(client.sendText(value), throwsA(isA<RokuException>()));
    }
    expect(fake.requests, isEmpty);
  });
  test(
    'partial text failure reports progress and never retries characters',
    () async {
      final fake = FakeTransport();
      fake.handler = (method, uri) {
        if (fake.commands.length == 3) throw const RokuException('Offline');
        return '';
      };
      final client = RokuClient('192.168.1.50', transport: fake);
      await expectLater(
        client.sendText('hello'),
        throwsA(
          isA<RokuException>().having(
            (e) => e.message,
            'message',
            contains('after 2 characters'),
          ),
        ),
      );
      expect(fake.commands, ['Lit_h', 'Lit_e', 'Lit_l']);
    },
  );
  test('malformed and non-Roku XML is rejected', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    for (final body in [
      '<broken',
      '<html>wrong service</html>',
      '<device-info/>',
    ]) {
      fake.handler = (_, __) => body;
      await expectLater(client.deviceInfo(), throwsA(isA<RokuException>()));
    }
  });
  test('closed clients cannot send later commands to an old TV', () async {
    final fake = FakeTransport();
    final client = RokuClient('192.168.1.50', transport: fake);
    client.close();
    await expectLater(client.key('Home'), throwsA(isA<RokuException>()));
    expect(fake.requests, isEmpty);
  });

  group('native transport', () {
    late HttpServer server;
    late NativeRokuTransport transport;
    setUp(() async {
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      transport = NativeRokuTransport();
    });
    tearDown(() async {
      transport.close();
      await server.close(force: true);
    });
    Uri endpoint() => Uri.parse(
      'http://127.0.0.1:' + server.port.toString() + '/keypress/Home',
    );

    test('POSTs have an empty body', () async {
      final body = Completer<List<int>>();
      server.listen((request) async {
        expect(request.method, 'POST');
        body.complete(
          await request.fold(<int>[], (all, chunk) => all..addAll(chunk)),
        );
        await request.response.close();
      });
      expect(await transport.send('POST', endpoint()), '');
      expect(await body.future, isEmpty);
    });
    test('redirects are rejected rather than followed', () async {
      var requests = 0;
      server.listen((request) async {
        requests++;
        request.response.statusCode = 302;
        request.response.headers.set('Location', '/should-not-follow');
        await request.response.close();
      });
      await expectLater(
        transport.send('GET', endpoint()),
        throwsA(isA<RokuException>()),
      );
      expect(requests, 1);
    });
    test('response size is bounded', () async {
      server.listen((request) async {
        request.response.write('x' * 262145);
        await request.response.close();
      });
      await expectLater(
        transport.send('GET', endpoint()),
        throwsA(isA<RokuException>()),
      );
    });
    test('timeouts do not automatically repeat a command', () async {
      var requests = 0;
      server.listen((request) {
        requests++;
      });
      await expectLater(
        transport.send(
          'POST',
          endpoint(),
          timeout: const Duration(milliseconds: 30),
        ),
        throwsA(isA<RokuException>()),
      );
      expect(requests, 1);
    });
  });
}
