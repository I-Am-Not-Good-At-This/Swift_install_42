#!/usr/bin/env python3
"""
Swift installer for /goinfre — École 42 Fedora machines
No sudo, no dnf. Extracts the Swift toolchain into /goinfre/<USER>/swift
and patches your shell rc file to add it to PATH.

Usage:
    python3 install_swift.py               # install
    python3 install_swift.py --check       # check if already installed
    python3 install_swift.py --clean       # remove installation
    python3 install_swift.py --path        # add Swift aliases to shell rc
    python3 install_swift.py --path-check  # check which Swift commands are in PATH
"""

import os
import sys
import shutil
import tarfile
import argparse
import subprocess
import urllib.request
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURATION — edit these if needed
# ─────────────────────────────────────────────

SWIFT_VERSION   = "6.2.4"                          # e.g. "6.2.4"
SWIFT_RELEASE   = f"swift-{SWIFT_VERSION}-RELEASE"
PLATFORM        = "fedora41"                        # fedora39 or fedora41 (works on 42 too)
ARCH            = "x86_64"                          # x86_64 or aarch64

TARBALL_NAME    = f"{SWIFT_RELEASE}-{PLATFORM}.tar.gz"
SIG_NAME        = f"{TARBALL_NAME}.sig"
BASE_URL        = (
    f"https://download.swift.org/"
    f"swift-{SWIFT_VERSION}-release/"
    f"{PLATFORM}/{SWIFT_RELEASE}"
)

GOINFRE_BASE    = Path("/goinfre")                  # mount point on 42 machines
USER            = os.environ.get("USER", "PLACEHOLDER_USERNAME")
INSTALL_DIR     = GOINFRE_BASE / USER / "swift"
DOWNLOAD_DIR    = GOINFRE_BASE / USER / ".swift_tmp"

# Shell rc files to patch — ALL that exist will be patched (bash + zsh)
SHELL_RC_CANDIDATES = [
    Path.home() / ".zshrc",
    Path.home() / ".bashrc",
    Path.home() / ".profile",
]

# PGP keys for signature verification (from swift.org/keys/active)
# Each tuple is (fingerprint, .asc download URL)
PGP_KEYS = [
    (
        "A62AE125BBBFBB96A6E042EC925CC1CCED3D1561",
        "https://swift.org/keys/release-key-swift-5.x.asc",        # Swift 5.x release key
    ),
    (
        "E813C892820A6FA137558268F167DF1ACF9CE069",
        "https://swift.org/keys/automatic-signing-key-4.asc",       # Automatic signing key #4
    ),
    (
        "52BB7E3DE28A71BE22EC05FFEF80A866B47A981F",
        "https://swift.org/keys/release-key-swift-6.x.asc",        # Swift 6.x release key
    ),
]

# ─────────────────────────────────────────────
# ALIASES
# ─────────────────────────────────────────────

# Every command Swift users expect, mapped to its binary or command.
# Aliases handle multi-word commands (e.g. swift build → sb) cleanly.
def swift_aliases():
    """Build alias map after INSTALL_DIR is known."""
    bin_dir = f"{INSTALL_DIR}/usr/bin"
    return {
        # Core binaries
        "swift":           f"{bin_dir}/swift",
        "swiftc":          f"{bin_dir}/swiftc",
        "sourcekit-lsp":   f"{bin_dir}/sourcekit-lsp",
        # SwiftPM shortcuts
        "sb":              f"{bin_dir}/swift build",
        "sr":              f"{bin_dir}/swift run",
        "st":              f"{bin_dir}/swift test",
        "sp":              f"{bin_dir}/swift package",
        "srepl":           f"{bin_dir}/swift repl",
        # Scaffolding
        "swift-new-exec":  f"{bin_dir}/swift package init --type executable",
        "swift-new-lib":   f"{bin_dir}/swift package init --type library",
    }

ALIAS_MARKER = "# swift-goinfre-aliases"

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

BOLD   = "\033[1m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
RED    = "\033[31m"
YELLOW = "\033[33m"
RESET  = "\033[0m"

def log(msg):    print(f"{CYAN}==>{RESET} {msg}")
def ok(msg):     print(f"{GREEN}  \u2713 {msg}{RESET}")
def warn(msg):   print(f"{YELLOW}  ! {msg}{RESET}")
def error(msg):  print(f"{RED}  \u2717 {msg}{RESET}")
def header(msg): print(f"\n{BOLD}{msg}{RESET}")


def source_hint(rcs):
    """Print a prominent, easy-to-copy source command for all patched rc files."""
    BG    = "\033[44m"   # blue background
    WHITE = "\033[97m"
    RESET_ALL = "\033[0m"
    print()
    for rc in rcs:
        cmd = f"source {rc}"
        print(f"  {BG}{WHITE} {cmd} {RESET_ALL}")
    print()


def run(cmd, check=True, capture=False):
    """Run a shell command, optionally capturing output."""
    return subprocess.run(
        cmd, shell=True, check=check,
        capture_output=capture, text=True
    )


def download_file(url: str, dest: Path):
    """Download url to dest with a simple progress indicator."""
    print(f"  Downloading {dest.name} ...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        print("done")
    except Exception as e:
        print()
        raise RuntimeError(f"Download failed: {e}") from e


def swift_binary() -> Path:
    return INSTALL_DIR / "usr" / "bin" / "swift"


def is_installed() -> bool:
    return swift_binary().exists()


def detect_shell_rcs():
    """Return all existing shell rc files (may be both .zshrc and .bashrc)."""
    return [rc for rc in SHELL_RC_CANDIDATES if rc.exists()]


def detect_shell_rc():
    """Return first existing rc file, or None. Kept for compatibility."""
    found = detect_shell_rcs()
    return found[0] if found else None


def patch_shell_rc():
    """Add Swift to PATH in all existing shell rc files, idempotent."""
    rcs = detect_shell_rcs()
    if not rcs:
        warn("No shell rc file found. Add this line manually:")
        print(f'    export PATH="{INSTALL_DIR}/usr/bin:$PATH"')
        return

    export_line = f'export PATH="{INSTALL_DIR}/usr/bin:$PATH"'
    marker = "# swift-goinfre"
    patched = []

    for rc in rcs:
        content = rc.read_text()
        if marker in content:
            ok(f"PATH already patched in {rc}")
        else:
            with rc.open("a") as f:
                f.write(f"\n{marker}\n{export_line}\n")
            ok(f"Patched {rc} with Swift PATH")
            patched.append(rc)

    if patched:
        source_hint(patched)


def verify_signature(tarball: Path, sig: Path) -> bool:
    """Verify PGP signature using an isolated GNUPGHOME to avoid shared keyboxd
    lock contention on multi-user machines (common on 42 clusters)."""
    if not shutil.which("gpg"):
        warn("gpg not found — skipping signature verification")
        return True

    import tempfile
    with tempfile.TemporaryDirectory() as tmp_gpg:
        # Isolated env: bypasses the shared keyboxd daemon entirely,
        # uses a plain file keyring only this process can touch.
        env = os.environ.copy()
        env["GNUPGHOME"] = tmp_gpg

        def gpg(cmd):
            return subprocess.run(
                cmd, shell=True, check=False,
                capture_output=True, text=True, env=env
            )

        log("Importing Swift PGP keys (isolated keyring)...")
        for fingerprint, asc_url in PGP_KEYS:
            r = subprocess.run(
                f"wget -q -O - {asc_url} | gpg --homedir {tmp_gpg} --import -",
                shell=True, check=False, capture_output=True, text=True
            )
            if r.returncode != 0:
                warn(f"wget import failed for {fingerprint[:16]}, trying keyserver...")
                gpg(f"gpg --keyserver hkp://keyserver.ubuntu.com --recv-keys {fingerprint}")

        result = gpg(f'gpg --verify "{sig}" "{tarball}"')
        if result.returncode == 0:
            ok("PGP signature verified")
            return True
        else:
            error("PGP signature verification FAILED — aborting for safety")
            error(result.stderr.strip())
            return False


# ─────────────────────────────────────────────
# MAIN ACTIONS
# ─────────────────────────────────────────────

def do_check():
    header("Swift install check")
    if is_installed():
        result = run(f'"{swift_binary()}" --version', capture=True, check=False)
        ok(f"Swift is installed at {INSTALL_DIR}")
        print(f"    {result.stdout.strip()}")
    else:
        warn(f"Swift is NOT installed in {INSTALL_DIR}")
        print("  Run this script without arguments to install.")
    sys.exit(0)


def do_clean():
    header("Removing Swift from /goinfre")
    if INSTALL_DIR.exists():
        shutil.rmtree(INSTALL_DIR)
        ok(f"Removed {INSTALL_DIR}")
    else:
        warn(f"Nothing to remove at {INSTALL_DIR}")

    if DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)
        ok(f"Removed temp dir {DOWNLOAD_DIR}")

    for rc in detect_shell_rcs():
        content = rc.read_text()
        if "# swift-goinfre" in content:
            lines = [l for l in content.splitlines()
                     if "# swift-goinfre" not in l
                     and str(INSTALL_DIR) not in l]
            rc.write_text("\n".join(lines) + "\n")
            ok(f"Removed PATH/alias entries from {rc}")
    sys.exit(0)


def do_install():
    header(f"Installing Swift {SWIFT_VERSION} \u2192 {INSTALL_DIR}")

    # 0. Pre-flight checks
    if USER == "PLACEHOLDER_USERNAME":
        error("Could not detect $USER. Set PLACEHOLDER_USERNAME manually at the top of this script.")
        sys.exit(1)

    if not GOINFRE_BASE.exists():
        error(f"{GOINFRE_BASE} does not exist on this machine.")
        error("Are you on an \u00c9cole 42 computer?")
        sys.exit(1)

    if is_installed():
        result = run(f'"{swift_binary()}" --version', capture=True, check=False)
        ok(f"Swift already installed: {result.stdout.strip()}")
        patch_shell_rc()
        sys.exit(0)

    # 1. Create directories
    log("Creating install directories...")
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    ok("Directories ready")

    # 2. Download tarball + signature
    header("Downloading Swift toolchain")
    tarball_path = DOWNLOAD_DIR / TARBALL_NAME
    sig_path     = DOWNLOAD_DIR / SIG_NAME

    if tarball_path.exists():
        ok("Tarball already downloaded, skipping")
    else:
        download_file(f"{BASE_URL}/{TARBALL_NAME}", tarball_path)

    download_file(f"{BASE_URL}/{SIG_NAME}", sig_path)

    # 3. Verify signature
    header("Verifying signature")
    if not verify_signature(tarball_path, sig_path):
        sys.exit(1)

    # 4. Extract
    header("Extracting toolchain")
    log(f"Extracting to {INSTALL_DIR} (this may take a minute)...")
    with tarfile.open(tarball_path, "r:gz") as tar:
        members = tar.getmembers()
        prefix = members[0].name.split("/")[0] + "/"
        for member in members:
            member.path = member.path.replace(prefix, "", 1)
            if member.path:
                tar.extract(member, path=INSTALL_DIR)
    ok("Extraction complete")

    # 5. Patch shell rc
    header("Configuring PATH")
    patch_shell_rc()

    # 6. Quick smoke test
    header("Smoke test")
    result = run(f'"{swift_binary()}" --version', capture=True, check=False)
    if result.returncode == 0:
        ok(f"Swift works: {result.stdout.strip()}")
    else:
        error("swift binary didn't run — something went wrong during extraction")
        sys.exit(1)

    # 7. Cleanup temp files
    log("Cleaning up downloaded files...")
    shutil.rmtree(DOWNLOAD_DIR)
    ok("Done")

    header("All done! \U0001f389")
    print(f"  Swift {SWIFT_VERSION} is installed at {INSTALL_DIR}")
    rc = detect_shell_rc()
    print(f"  Then: swift --version")
    print()
    print("  Tip: re-run this script on any new 42 machine to reinstall in ~1 min.")
    print("  Tip: run --path to set up command aliases (sb, sr, st, ...)")


def do_path():
    """Write Swift aliases into the shell rc file."""
    header("Setting up Swift aliases")

    if not is_installed():
        warn("Swift doesn't seem to be installed yet. Run the script without flags first.")
        warn(f"Expected binary: {swift_binary()}")

    rc = detect_shell_rc()
    if rc is None:
        error("No shell rc file found. Create ~/.zshrc or ~/.bashrc first.")
        sys.exit(1)

    aliases = swift_aliases()
    # Build alias block
    alias_lines = [ALIAS_MARKER]
    for name, target in aliases.items():
        alias_lines.append(f"alias {name}='{target}'")
    alias_block = "\n" + "\n".join(alias_lines) + "\n"

    # Patch all existing rc files
    rcs = detect_shell_rcs()
    if not rcs:
        error("No shell rc file found. Create ~/.zshrc or ~/.bashrc first.")
        sys.exit(1)

    patched = []
    for rc in rcs:
        rc_content = rc.read_text()
        # Remove stale alias block first (idempotent)
        if ALIAS_MARKER in rc_content:
            filtered = []
            skip = False
            for line in rc_content.splitlines():
                if line.strip() == ALIAS_MARKER:
                    skip = True
                elif skip and line.startswith("alias "):
                    continue
                else:
                    skip = False
                    filtered.append(line)
            rc_content = "\n".join(filtered).rstrip() + "\n"
        rc_content += alias_block
        rc.write_text(rc_content)
        ok(f"Written {len(aliases)} aliases to {rc}")
        patched.append(rc)

    print()
    for name, target in aliases.items():
        print(f"    {name:<18} \u2192 {target}")

    source_hint(patched)
    sys.exit(0)


def do_path_check():
    """Report which Swift commands are visible in the current PATH."""
    header("Swift PATH check")

    aliases = swift_aliases()
    all_good = True
    for name in aliases:
        found = shutil.which(name)
        if found:
            ok(f"{name:<18} {found}")
        else:
            warn(f"{name:<18} not found in PATH")
            all_good = False

    print()
    if all_good:
        ok("All Swift commands are reachable.")
    else:
        rc = detect_shell_rc()
        warn("Some commands are missing. Run:  python3 install_swift.py --path")
        source_hint(detect_shell_rcs() or [Path('~/.zshrc')])
    sys.exit(0)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Swift installer for /goinfre")
    parser.add_argument("--check",      action="store_true", help="Check if Swift is installed")
    parser.add_argument("--clean",      action="store_true", help="Remove Swift from /goinfre")
    parser.add_argument("--path",       action="store_true", help="Add Swift aliases to shell rc")
    parser.add_argument("--path-check", action="store_true", help="Check which Swift commands are in PATH",
                        dest="path_check")
    args = parser.parse_args()

    if args.check:
        do_check()
    elif args.clean:
        do_clean()
    elif args.path:
        do_path()
    elif args.path_check:
        do_path_check()
    else:
        do_install()