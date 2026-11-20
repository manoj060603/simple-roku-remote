import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:simple_roku_remote/main.dart';
import 'package:simple_roku_remote/remote_controller.dart';
import 'package:simple_roku_remote/roku.dart';
import 'support/fakes.dart';

Future<void> screenshot(WidgetTester tester, GlobalKey key, String name) async {
  if (!const bool.fromEnvironment('CAPTURE_SCREENSHOTS')) return;
  await tester.runAsync(() async {
    final boundary = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    final image = await boundary.toImage(pixelRatio: 1);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    Directory('screenshots').createSync();
    await File('screenshots/$name.png').writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

void main() {
  testWidgets('a phone connects, types directly, and exposes power and keyboard controls', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final fake = FakeTransport(), store = MemoryTvStore();
    final controller = RemoteController(clientFactory: (host) => RokuClient(host, transport: fake), delay: (_) async {});
    final image = GlobalKey();
    await tester.pumpWidget(RepaintBoundary(key: image, child: SimpleRemoteApp(store: store, controller: controller)));
    await tester.pumpAndSettle();
    await screenshot(tester, image, 'mobile-connect');
    await tester.enterText(find.byKey(const Key('tv-address')), '192.168.1.50');
    await tester.tap(find.byKey(const Key('connect-tv')));
    await tester.pumpAndSettle();
    expect(store.value, '192.168.1.50');
    expect(find.text('Turn TV on'), findsOneWidget);
    expect(find.text('Type on TV'), findsOneWidget);
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await screenshot(tester, image, 'mobile-remote');
    await tester.enterText(find.byKey(const Key('tv-text')), 'Riemann hypothesis');
    await tester.tap(find.byKey(const Key('send-text')));
    await tester.pumpAndSettle();
    expect(fake.commands.where((key) => key.startsWith('Lit_')).map((key) => key.substring(4)).join(), 'Riemann hypothesis');
    expect(tester.widget<TextField>(find.byKey(const Key('tv-text'))).controller!.text, '');
    await tester.tap(find.text('Keyboard'));
    await tester.pumpAndSettle();
    expect(find.text('Press OK on TV'), findsOneWidget);
    FocusManager.instance.primaryFocus?.unfocus();
    await tester.pumpAndSettle();
    await screenshot(tester, image, 'mobile-keyboard');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('a saved offline TV still has a working wake button', (tester) async {
    final fake = FakeTransport();
    fake.handler = (_, __) => throw const RokuException('TV unavailable');
    final controller = RemoteController(clientFactory: (host) => RokuClient(host, transport: fake), delay: (_) async {});
    await tester.pumpWidget(SimpleRemoteApp(store: MemoryTvStore('192.168.1.50'), controller: controller));
    await tester.pumpAndSettle();
    expect(find.text('Turn TV on'), findsOneWidget);
    fake.handler = null;
    await tester.tap(find.byKey(const Key('power-on')));
    await tester.pumpAndSettle();
    expect(fake.commands, ['PowerOn']);
    expect(controller.info?.isOn, isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('remote and app controls fit a small phone', (tester) async {
    tester.view.physicalSize = const Size(320, 720);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final fake = FakeTransport();
    final controller = RemoteController(clientFactory: (host) => RokuClient(host, transport: fake));
    await tester.pumpWidget(SimpleRemoteApp(store: MemoryTvStore('192.168.1.50'), controller: controller));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('Apps'));
    await tester.pumpAndSettle();
    expect(find.text('HDMI 1'), findsOneWidget);
    expect(find.text('YouTube'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
