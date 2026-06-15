# CS2 Server Picker for macOS

Lists Steam Datagram Relay (SDR) servers, measures ping, and blocks relays via the macOS `pf` firewall.

Inspired by the original Windows [cs2-server-picker](https://github.com/FN-FAL113/cs2-server-picker).

## Project structure

```
.
├── src/cs2_picker/
│   ├── __main__.py          # python -m cs2_picker
│   ├── _version.py          # written from git tag at build time
│   ├── core/                # config, constants
│   ├── services/            # server, firewall, ping, update
│   └── ui/                  # main window
├── scripts/
│   ├── run.sh               # dev mode
│   ├── build.sh             # build .app
│   ├── release.sh           # create git tag
│   └── write_version.py     # embed version
├── packaging/
│   └── CS2ServerPicker.spec
└── .github/workflows/       # CI + Release
```

## Development

```bash
chmod +x scripts/run.sh
./scripts/run.sh
```

## Build macOS .app

```bash
chmod +x scripts/build.sh
./scripts/build.sh
```

Local builds use the latest git tag for version (or `0.0.0-dev` if none).

## Release

Version source of truth: **git tag** (no `VERSION` file).

```bash
chmod +x scripts/release.sh
./scripts/release.sh 1.0.2
git push origin v1.0.2
```

When `v1.0.2` is pushed, GitHub Actions will:

1. Read `1.0.2` from the tag
2. Embed it in `_version.py` and the `.app` Info.plist
3. Build `.zip` and `.dmg`
4. Publish a GitHub Release

## Updates

The app checks GitHub Releases every 60 seconds. If a newer version exists, an **Update** button appears in the sidebar. Updates install only when you click the button (no silent auto-update).

## Requirements

- macOS 11+
- **Python 3.11 or 3.12** (Homebrew Python 3.14 is not supported — pyexpat issue)
- Administrator password (firewall rules)

Python 3.12:

```bash
brew install python@3.12
rm -rf .venv && ./scripts/build.sh
```

Alternative — `uv` downloads Python 3.12 automatically:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
rm -rf .venv && ./scripts/build.sh
```

**Xcode Command Line Tools** are required to build the `.app` (PyInstaller uses `lipo`):

```bash
xcode-select --install
```

## Disclaimer

This project is not affiliated with Valve.
