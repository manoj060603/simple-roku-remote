import 'package:shared_preferences/shared_preferences.dart';

abstract interface class TvStore {
  Future<String?> load();
  Future<void> save(String host);
  Future<void> clear();
}

class PhoneTvStore implements TvStore {
  final SharedPreferencesAsync _prefs = SharedPreferencesAsync();
  @override
  Future<String?> load() => _prefs.getString('roku_tv_address');
  @override
  Future<void> save(String host) => _prefs.setString('roku_tv_address', host);
  @override
  Future<void> clear() => _prefs.remove('roku_tv_address');
}
