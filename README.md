# Pyswift in /goinfre

Installs Swift into `/goinfre/$USER/swift` — no sudo, no dnf.
Made for École 42 Fedora machines where `/goinfre` is local and not accessible throuhgout sessions. We decided to install it in the */goinfre* to gain some space. This implies that you check on your computer if this was already installed. **Therefore, it is almost mandatory to run --check before reinstalling !**

## Usage

```bash
python3 install_swift.py          # install Swift
python3 install_swift.py --check  # is Swift installed on this machine?
python3 install_swift.py --clean  # remove everything from /goinfre
python3 install_swift.py --path        # writes aliases to your shell rc
python3 install_swift.py --path-check  # shows which commands are findable in PATH
```

After installing, reload your shell:

```bash
source ~/.zshrc   # or ~/.bashrc
swift --version   # should print Swift x.x.x
```

## First time on a new machine

Just re-run the script. It takes ~1–2 min depending on network speed.
It won't re-download the tarball if it's already cached, and won't reinstall if Swift is already there.

## Configuration

Edit the top of `install_swift.py` if you need to change anything:

| Variable | Default | Notes |
|---|---|---|
| `SWIFT_VERSION` | `6.2.4` | Update when new Swift versions release |
| `PLATFORM` | `fedora41` | Also works on Fedora 42 |
| `ARCH` | `x86_64` | Change to `aarch64` if needed |
| `GOINFRE_BASE` | `/goinfre` | Adjust if your campus uses a different path |

## What gets installed

- `swift` — REPL and script runner
- `swiftc` — compiler
- `swift package` / `swift build` / `swift test` — package manager
- `sourcekit-lsp` — language server (for VS Code autocomplete)

## Notes

- `/goinfre` is local to each machine, so you need to re-run the script each time you switch computers.
- Your shell rc (`~/.zshrc` or `~/.bashrc`) is patched once and never duplicated.
- PGP signature verification runs automatically if `gpg` is available.
