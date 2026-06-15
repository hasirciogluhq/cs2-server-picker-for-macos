# CS2 Server Picker for macOS

Steam Datagram Relay (SDR) sunucularını listeler, ping ölçer ve macOS `pf` firewall ile engeller.

## Proje yapısı

```
.
├── src/cs2_picker/          # Uygulama kaynak kodu
│   ├── __main__.py          # python -m cs2_picker
│   ├── _version.py          # Build sırasında tag'den yazılır
│   ├── core/                # config, constants
│   ├── services/            # server, firewall, ping
│   └── ui/                  # arayüz
├── scripts/
│   ├── run.sh               # geliştirme
│   ├── build.sh             # .app derleme
│   ├── release.sh           # tag oluştur
│   └── write_version.py     # versiyon gömme
├── packaging/
│   └── CS2ServerPicker.spec # PyInstaller
└── .github/workflows/       # CI + Release
```

## Geliştirme

```bash
chmod +x scripts/run.sh
./scripts/run.sh
```

## macOS .app derleme

```bash
chmod +x scripts/build.sh
./scripts/build.sh
```

Yerel build son tag'den versiyon alır (yoksa `0.0.0-dev`).

## Release

Versiyon **tek kaynak: git tag**. `VERSION` dosyası yok.

```bash
chmod +x scripts/release.sh
./scripts/release.sh 1.0.2
git push origin v1.0.2
```

`v1.0.2` push edilince GitHub Actions:

1. Tag'den `1.0.2` okur
2. `_version.py` ve `.app` Info.plist'e gömer
3. `.zip` + `.dmg` oluşturur
4. GitHub Release yayınlar

## Gereksinimler

- macOS 11+
- **Python 3.11 veya 3.12** (Homebrew Python 3.14 desteklenmiyor — pyexpat hatası)
- Admin şifresi (firewall)

Python 3.12:

```bash
brew install python@3.12
rm -rf .venv && ./scripts/build.sh
```

Alternatif — `uv` Python 3.12'yi otomatik indirir:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
rm -rf .venv && ./scripts/build.sh
```

`.app` derlemesi icin **Xcode Command Line Tools** (lipo):

```bash
xcode-select --install
```

## Uyarı

Bu proje Valve ile bağlantılı değildir.
