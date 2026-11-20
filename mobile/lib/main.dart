import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'preferences.dart';
import 'remote_controller.dart';
import 'roku.dart';

const mint = Color(0xffa4f1ce);
const background = Color(0xff0b1116);
const panel = Color(0xff17232c);
const muted = Color(0xffa9b7c1);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SimpleRemoteApp());
}

class SimpleRemoteApp extends StatelessWidget {
  const SimpleRemoteApp({super.key, this.store, this.controller});
  final TvStore? store;
  final RemoteController? controller;
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: 'Simple Roku Remote',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      colorScheme: const ColorScheme.dark(primary: mint, onPrimary: Color(0xff14291f), surface: panel),
      inputDecorationTheme: InputDecorationTheme(
        filled: true, fillColor: panel,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(14)),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: Color(0xff415663))),
      ),
      filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(minimumSize: const Size(48, 50), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)))),
      outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(minimumSize: const Size(48, 50), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)))),
    ),
    home: RemoteHome(store: store ?? PhoneTvStore(), controller: controller),
  );
}

enum RemoteTab { remote, apps, keyboard }

class RemoteHome extends StatefulWidget {
  const RemoteHome({super.key, required this.store, this.controller});
  final TvStore store;
  final RemoteController? controller;
  @override
  State<RemoteHome> createState() => _RemoteHomeState();
}

class _RemoteHomeState extends State<RemoteHome> with WidgetsBindingObserver {
  late final RemoteController remote = widget.controller ?? RemoteController();
  final address = TextEditingController();
  final text = TextEditingController();
  RemoteTab tab = RemoteTab.remote;
  bool restoring = true;
  bool editingAddress = false;
  bool textSending = false;
  bool foreground = true;
  String? formError;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    remote.addListener(_changed);
    timer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (foreground && !editingAddress) unawaited(remote.refresh());
    });
    unawaited(_restore());
  }

  void _changed() { if (mounted) setState(() {}); }

  Future<void> _restore() async {
    String? saved;
    try { saved = await widget.store.load(); } catch (_) {}
    if (!mounted) return;
    setState(() { restoring = false; });
    if (saved != null) {
      address.text = saved;
      await _connect(save: false);
    }
  }

  void _notice(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _save() async {
    if (remote.host == null) return;
    try { await widget.store.save(remote.host!); }
    catch (_) { _notice('Connected. This phone could not remember the TV address.'); }
  }

  Future<void> _connect({bool save = true}) async {
    try {
      final host = validateTvAddress(address.text);
      text.clear();
      setState(() { formError = null; editingAddress = false; });
      final ok = await remote.connect(host);
      if (ok && save) await _save();
    } on RokuException catch (failure) {
      if (mounted) setState(() { formError = failure.message; });
    }
  }

  Future<void> _send() async {
    final value = text.text;
    if (value.trim().isEmpty || textSending) return;
    setState(() { textSending = true; });
    final ok = await remote.type(value);
    if (!mounted) return;
    setState(() { textSending = false; });
    if (ok) {
      if (text.text == value) text.clear();
      _notice('Text sent. Press OK on the TV if needed.');
    }
  }

  Future<void> _powerOn() async {
    if (await remote.turnOn()) await _save();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    foreground = state == AppLifecycleState.resumed;
    if (foreground && !editingAddress) unawaited(remote.refresh());
  }

  @override
  void dispose() {
    timer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    remote.removeListener(_changed);
    remote.dispose();
    address.dispose();
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    body: SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: SingleChildScrollView(
            key: const Key('remote-scroll'),
            padding: const EdgeInsets.fromLTRB(22, 24, 22, 30),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              const Text('SIMPLE ROKU REMOTE', style: TextStyle(color: muted, fontSize: 12, letterSpacing: 2.2, fontWeight: FontWeight.w700)),
              const SizedBox(height: 24),
              if (restoring) const Center(child: CircularProgressIndicator())
              else if (remote.host == null || editingAddress) ..._setup()
              else ..._controls(),
            ]),
          ),
        ),
      ),
    ),
  );

  List<Widget> _setup() => [
    const Text('Your phone.\nYour remote.', style: TextStyle(fontSize: 36, height: 1.12, fontWeight: FontWeight.w700, letterSpacing: -1)),
    const SizedBox(height: 15),
    const Text('Connect directly to your Roku over Wi-Fi.\nNo laptop or account needed.', style: TextStyle(color: muted, fontSize: 16, height: 1.5)),
    const SizedBox(height: 30),
    TextField(
      key: const Key('tv-address'),
      controller: address,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')), LengthLimitingTextInputFormatter(15)],
      textInputAction: TextInputAction.go,
      autocorrect: false,
      decoration: InputDecoration(labelText: 'TV IP address', hintText: '192.168.1.50', errorText: formError),
      onSubmitted: (_) => _connect(),
    ),
    const SizedBox(height: 16),
    FilledButton(key: const Key('connect-tv'), onPressed: remote.connecting ? null : () => _connect(), child: const Text('Connect to TV')),
    const SizedBox(height: 16),
    const Text('On the TV, find its address in Settings → Network → About. Keep your phone on the same Wi-Fi. Allow Local Network access if your phone asks.', style: TextStyle(color: muted, height: 1.6)),
    const SizedBox(height: 12),
    if (remote.host != null) TextButton(onPressed: () => setState(() { editingAddress = false; }), child: const Text('Back to remote')),
    if (remote.host != null) TextButton(onPressed: () async {
      await widget.store.clear();
      remote.disconnect();
      address.clear();
      text.clear();
      if (mounted) setState(() { editingAddress = false; });
    }, child: const Text('Forget TV')),
    const SizedBox(height: 24),
    _aboutButton(),
  ];

  List<Widget> _controls() {
    final info = remote.info;
    final status = remote.connecting ? 'Connecting…'
        : remote.activity ?? (!remote.reachable ? 'TV unavailable'
        : info?.isStandby == true ? 'Standby · tap Turn TV on'
        : 'Connected · ' + (info?.model ?? 'Roku'));
    return [
      Row(children: [
        Expanded(child: Text(info?.name ?? 'Your Roku', maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 30, height: 1.15, letterSpacing: -1, fontWeight: FontWeight.w700))),
        IconButton(tooltip: 'Change TV', onPressed: () {
          address.text = remote.host ?? '';
          setState(() { editingAddress = true; });
        }, icon: const Icon(Icons.settings_outlined, color: muted)),
      ]),
      const SizedBox(height: 9),
      Semantics(liveRegion: true, child: Row(children: [
        Icon(Icons.circle, size: 8, color: remote.reachable ? mint : const Color(0xffe5b176)),
        const SizedBox(width: 8),
        Expanded(child: Text(status, style: const TextStyle(color: muted, fontSize: 14))),
      ])),
      const SizedBox(height: 20),
      Row(children: [
        Expanded(child: FilledButton.icon(key: const Key('power-on'), onPressed: remote.canControl && remote.pending == 0 ? _powerOn : null, icon: const Icon(Icons.power_settings_new), label: const Text('Turn TV on'))),
        const SizedBox(width: 10),
        OutlinedButton(key: const Key('power-off'), onPressed: remote.canControl && remote.pending == 0 ? () => remote.turnOff() : null, child: const Text('Turn off')),
      ]),
      if (remote.error != null) Padding(
        padding: const EdgeInsets.only(top: 14),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(color: const Color(0xff30291e), borderRadius: BorderRadius.circular(14)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Semantics(liveRegion: true, child: Text(remote.error!, style: const TextStyle(color: Color(0xffffd7aa), height: 1.45))),
            TextButton(onPressed: () => remote.refresh(reloadApps: true), child: const Text('Try connection again')),
          ]),
        ),
      ),
      const SizedBox(height: 20),
      SegmentedButton<RemoteTab>(
        segments: const [
          ButtonSegment(value: RemoteTab.remote, label: Text('Remote')),
          ButtonSegment(value: RemoteTab.apps, label: Text('Apps')),
          ButtonSegment(value: RemoteTab.keyboard, label: Text('Keyboard')),
        ],
        showSelectedIcon: false,
        selected: {tab},
        onSelectionChanged: (value) => setState(() { tab = value.first; }),
      ),
      const SizedBox(height: 22),
      if (tab == RemoteTab.remote) ..._remotePanel(),
      if (tab == RemoteTab.apps) ..._appsPanel(),
      if (tab == RemoteTab.keyboard) ..._keyboardPanel(),
      const SizedBox(height: 26),
      _aboutButton(),
      const Text('Direct to your TV over Wi-Fi. No laptop needed.', textAlign: TextAlign.center, style: TextStyle(color: muted, fontSize: 12)),
    ];
  }

  Widget _textInput({bool expanded = false}) => TextField(
    key: const Key('tv-text'),
    controller: text,
    enabled: remote.canControl,
    maxLength: 80,
    minLines: expanded ? 4 : 1,
    maxLines: expanded ? 4 : 1,
    textInputAction: TextInputAction.send,
    autocorrect: false,
    enableSuggestions: false,
    decoration: InputDecoration(labelText: expanded ? 'Send text to TV' : null, hintText: 'Search or enter text', counterText: expanded ? null : ''),
    onSubmitted: (_) => _send(),
  );

  List<Widget> _remotePanel() => [
    const Text('Type on TV', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
    const SizedBox(height: 9),
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Expanded(child: _textInput()),
      const SizedBox(width: 8),
      FilledButton(key: const Key('send-text'), onPressed: remote.canControl && !textSending ? _send : null, child: const Text('Send')),
    ]),
    const SizedBox(height: 8),
    const Text('First open a search or text box on the TV.', style: TextStyle(color: muted, fontSize: 14)),
    const SizedBox(height: 24),
    Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
      _key('Back', Icons.keyboard_return_rounded, 'Back'),
      _key('Home', Icons.home_outlined, 'Home'),
      _key('Info', Icons.more_horiz, 'Options'),
    ]),
    const SizedBox(height: 18),
    _directionPad(),
    const SizedBox(height: 20),
    Container(
      decoration: BoxDecoration(color: panel, borderRadius: BorderRadius.circular(18)),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        _key('VolumeDown', Icons.remove, 'Volume down', width: 76),
        _key('VolumeMute', Icons.volume_off_outlined, 'Mute', width: 76),
        _key('VolumeUp', Icons.add, 'Volume up', width: 76),
      ]),
    ),
    const SizedBox(height: 14),
    Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
      _key('Rev', Icons.fast_rewind_rounded, 'Rewind'),
      _key('Play', Icons.play_arrow_rounded, 'Play or pause'),
      _key('Fwd', Icons.fast_forward_rounded, 'Fast forward'),
    ]),
    const SizedBox(height: 24),
    if (_shortcuts().isNotEmpty) ...[
      const Text('QUICK OPEN', style: TextStyle(color: muted, fontSize: 12, letterSpacing: 1.4)),
      const SizedBox(height: 10),
      Row(children: _shortcuts().map((app) => Expanded(child: Padding(padding: const EdgeInsets.symmetric(horizontal: 3), child: _appButton(app)))).toList()),
    ],
  ];

  List<TvApp> _shortcuts() {
    final result = <TvApp>[];
    for (final name in ['youtube', 'netflix', 'prime']) {
      final matching = remote.apps.where((app) => app.name.toLowerCase().contains(name));
      if (matching.isNotEmpty) result.add(matching.first);
    }
    return result;
  }

  Widget _directionPad() => Center(child: Container(
    width: 266, height: 266,
    decoration: BoxDecoration(
      shape: BoxShape.circle,
      border: Border.all(color: const Color(0xff364b58)),
      gradient: const LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xff273b46), Color(0xff14212a)]),
    ),
    child: Stack(alignment: Alignment.center, children: [
      Align(alignment: const Alignment(0, -.85), child: _key('Up', Icons.keyboard_arrow_up, 'Up', width: 76, height: 76, transparent: true)),
      Align(alignment: const Alignment(-.85, 0), child: _key('Left', Icons.keyboard_arrow_left, 'Left', width: 76, height: 76, transparent: true)),
      Align(alignment: const Alignment(.85, 0), child: _key('Right', Icons.keyboard_arrow_right, 'Right', width: 76, height: 76, transparent: true)),
      Align(alignment: const Alignment(0, .85), child: _key('Down', Icons.keyboard_arrow_down, 'Down', width: 76, height: 76, transparent: true)),
      SizedBox(width: 70, height: 70, child: FilledButton(
        style: FilledButton.styleFrom(shape: const CircleBorder(), padding: EdgeInsets.zero),
        onPressed: remote.canControl ? () => remote.press('Select') : null,
        child: const Text('OK', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
      )),
    ]),
  ));

  Widget _key(String key, IconData icon, String label, {double width = 74, double height = 50, bool transparent = false}) => Semantics(
    button: true, label: label,
    child: SizedBox(width: width, height: height, child: IconButton(
      tooltip: label,
      style: IconButton.styleFrom(backgroundColor: transparent ? Colors.transparent : panel, shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16))),
      iconSize: 27,
      onPressed: remote.canControl ? () => remote.press(key) : null,
      icon: Icon(icon),
    )),
  );

  Widget _appButton(TvApp app) => OutlinedButton(
    style: OutlinedButton.styleFrom(minimumSize: const Size(0, 64), padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12), foregroundColor: app.name.toLowerCase().contains('netflix') ? const Color(0xffff7685) : mint),
    onPressed: remote.canControl ? () => remote.launch(app.id) : null,
    child: Text(app.name, textAlign: TextAlign.center, maxLines: 3, overflow: TextOverflow.ellipsis),
  );

  List<Widget> _appsPanel() => [
    if (remote.info?.isTv == true) ...[
      const Text('TV INPUTS', style: TextStyle(color: muted, letterSpacing: 1.4, fontSize: 12)),
      const SizedBox(height: 10),
      Row(children: [1, 2, 3].map((number) => Expanded(child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: OutlinedButton(onPressed: remote.canControl ? () => remote.press('InputHDMI$number') : null, child: Text('HDMI $number')),
      ))).toList()),
      const SizedBox(height: 24),
    ],
    Row(children: [
      const Expanded(child: Text('YOUR APPS', style: TextStyle(color: muted, letterSpacing: 1.4, fontSize: 12))),
      IconButton(tooltip: 'Refresh apps', onPressed: () => remote.refresh(reloadApps: true), icon: const Icon(Icons.refresh)),
    ]),
    if (remote.apps.isEmpty) const Text('No shortcuts loaded. You can still use Home and the directional pad.', style: TextStyle(color: muted, height: 1.5)),
    for (var i = 0; i < remote.apps.length; i += 2) Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(children: [
        Expanded(child: _appButton(remote.apps[i])),
        const SizedBox(width: 10),
        Expanded(child: i + 1 < remote.apps.length ? _appButton(remote.apps[i + 1]) : const SizedBox()),
      ]),
    ),
  ];

  List<Widget> _keyboardPanel() => [
    const Text('Select a search or text field on the TV first. Text entry depends on the TV app.', style: TextStyle(color: muted, height: 1.6)),
    const SizedBox(height: 16),
    _textInput(expanded: true),
    const SizedBox(height: 12),
    Row(children: [
      Expanded(child: OutlinedButton(onPressed: remote.canControl ? () => remote.press('Backspace') : null, child: const Text('Delete'))),
      const SizedBox(width: 10),
      Expanded(child: FilledButton(key: const Key('send-text'), onPressed: remote.canControl && !textSending ? _send : null, child: const Text('Send text'))),
    ]),
    const SizedBox(height: 10),
    OutlinedButton(onPressed: remote.canControl ? () => remote.press('Select') : null, child: const Text('Press OK on TV')),
    const SizedBox(height: 14),
    const Text('Up to 80 characters. Text goes only to the TV and is not saved.', style: TextStyle(color: muted, height: 1.5, fontSize: 14)),
  ];

  Widget _aboutButton() => TextButton(onPressed: () => showAboutDialog(
    context: context,
    applicationName: 'Simple Roku Remote',
    applicationVersion: '0.2.0',
    applicationLegalese: 'MIT licensed · Copyright 2026 Manoj',
    children: const [
      SizedBox(height: 14),
      Text('Independent open source project. Not affiliated with Roku. The app connects directly to the TV; it does not use a cloud relay or laptop.'),
      SizedBox(height: 12),
      Text('Only the TV address is saved on your phone. Typed text is not stored. Roku control uses unencrypted HTTP on your local Wi-Fi.'),
      SizedBox(height: 12),
      SelectableText('https://github.com/manoj060603/simple-roku-remote'),
    ],
  ), child: const Text('Open source · MIT'));
}
