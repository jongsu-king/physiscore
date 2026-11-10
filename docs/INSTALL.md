# Installing Physiscore

Every release on the [Releases page](https://github.com/jongsu-king/physiscore/releases/latest) carries ready-to-run builds for Windows, macOS and Linux - Python is **not** needed for them - plus a `SHA256SUMS.txt` with the checksum of every file. The newest release is always at <https://github.com/jongsu-king/physiscore/releases/latest>.

## Which file do I need?

| Your computer | File | Notes |
|---|---|---|
| Windows 10 or 11, 64-bit | `Physiscore-<version>-windows-x64-setup.exe` | Installer (recommended). No administrator rights needed. |
| Windows, no installation | `Physiscore-<version>-windows-x64-portable.zip` | Unzip and run `Physiscore.exe`. Updates itself when the folder is writable. |
| Mac with Apple silicon (M1, M2, M3, M4) | `Physiscore-<version>-macos-arm64.dmg` | macOS 11 Big Sur or newer. |
| Mac with an Intel processor | `Physiscore-<version>-macos-x86_64.dmg` | macOS 11 or newer. |
| Ubuntu 22.04+, Debian 12+, Mint 21+ (x86-64) | `physiscore_<version>_amd64.deb` | System-wide package with a menu entry. |
| Other Linux (x86-64, glibc 2.35+) | `Physiscore-<version>-linux-x86_64.tar.gz` | Per-user install with `install.sh`, or run in place. |

Not sure which Mac you have? Apple menu → **About This Mac**: *Chip Apple M…* means Apple silicon, *Processor Intel…* means Intel.

## Windows

**Installer**

1. Download `Physiscore-<version>-windows-x64-setup.exe` and run it.
2. If SmartScreen says *Windows protected your PC*, click **More info → Run anyway**
   (the build is not code-signed; compare the SHA-256 below if you want to be sure).
3. Choose *Install for me only* (default, no administrator rights) or *Install for all
   users*. The program appears in the Start menu as **Physiscore**.

Uninstall from **Settings → Apps → Installed apps → Physiscore → Uninstall**. Your
settings in `%APPDATA%\Physiscore` are left in place; delete that folder to remove
them too.

Unattended installation (for IT departments):
`Physiscore-<version>-windows-x64-setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER`
(or `/ALLUSERS` from an elevated prompt; `/DIR="D:\Apps\Physiscore"` picks the folder).

**Portable zip**

Unzip `Physiscore-<version>-windows-x64-portable.zip` anywhere (for example a USB stick) and
run `Physiscore.exe` inside the folder. Nothing is written to the registry.

## macOS

1. Download the `.dmg` for your processor (see the table above) and open it.
2. Drag **Physiscore.app** onto the **Applications** folder shown next to it.
3. Eject the disk image and start the program from Applications or Launchpad.
4. The first start of an unsigned build shows *"Physiscore" cannot be
   opened because Apple cannot check it for malicious software*. Click **Done**, open
   **System Settings → Privacy & Security**, scroll down and click **Open Anyway**,
   then confirm. On macOS 14 and older, right-click the app → **Open** also works.
   From a terminal: `xattr -dr com.apple.quarantine "/Applications/Physiscore.app"`.

Keep the app in **Applications** (or another folder you can write to) - an app started
directly from the disk image or from Downloads runs from a read-only location
("App Translocation") and can only tell you about updates, not install them.

Uninstall: drag **Physiscore.app** to the Trash. Settings live in
`~/Library/Application Support/Physiscore`.

## Linux

**Debian, Ubuntu, Linux Mint (.deb)**

```bash
sudo apt install ./physiscore_<version>_amd64.deb
```

The program is installed in `/opt/physiscore`, the command `physiscore` is put on the PATH and a
menu entry is added. Remove it with `sudo apt remove physiscore`.

**Any distribution (.tar.gz)**

```bash
tar -xzf Physiscore-<version>-linux-x86_64.tar.gz
Physiscore/install.sh          # installs for the current user, no root
```

`install.sh` copies the program to `~/.local/share/physiscore`, links
`~/.local/bin/physiscore` and adds a menu entry. `uninstall.sh` (in the same folder)
removes all three. You can also run `Physiscore/Physiscore` without installing.
Settings live in `~/.config/Physiscore`.

The Origin export (Windows COM automation) is available on Windows only; every analysis and the CSV/Excel/PNG exports work on all three systems. The interpretation panels are rule-based and work offline on every system; no account or key is needed.

## From source (Python)

Python 3.10+; see the README for details.

```bash
git clone https://github.com/jongsu-king/physiscore.git
cd physiscore
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python Physiscore_Launcher.py
```

Update a source checkout with `git pull` and `pip install -r requirements.txt`.

The command line (`python physiscore_cli.py --help`) runs every analysis without the
GUI; an installed program offers `Physiscore --tool "J-V Curve"`, `--spectra XRD|PL|XPS`,
`--selftest`, `--update` and `--version`.

## Automatic updates

The installed program keeps itself up to date. The setting is in two places: the **Updates**
tab of the main window and **Tools → Updates → Automatic updates**. There are three
settings:

| Setting | What happens |
|---|---|
| **Download and install automatically** (default) | Once a day, a few seconds after start-up, the program asks GitHub for the latest release. If it is newer, the file for your system is downloaded in the background and checked against the release's `SHA256SUMS.txt`. You are then asked whether to restart now; otherwise the update is installed when you close the program. |
| **Only tell me about new versions** | The same daily check, but nothing is downloaded until you agree. |
| **Off** | No automatic check. **Tools → Updates → Check for updates…** still works. |

**What is installed, per platform**

| Installed from | How the update is applied |
|---|---|
| Windows installer | the new `-setup.exe` runs silently (`/VERYSILENT`) into the same folder, then the program starts again |
| Windows portable zip | the program folder is replaced by the new one after the program exits |
| macOS disk image | the new `.dmg` is mounted, the app is copied next to the old one and swapped in after the program exits |
| Linux `install.sh` | `~/.local/share/physiscore` is replaced after the program exits |
| Linux `.deb` | `pkexec apt-get install` asks for your password once and upgrades the package |
| pip / source checkout | nothing is changed; the program shows the command (`pip install -U …` or `git pull`) |

**Privacy and safety**

- One HTTPS request to `api.github.com/repos/jongsu-king/physiscore/releases/latest` per day; the only
  information sent is the `User-Agent` `<program>/<version>`. No account, no tracking.
- A downloaded file is used only if its SHA-256 equals the value in the release's
  `SHA256SUMS.txt`; otherwise it is deleted. A release without that file is never
  installed automatically.
- The previous version is kept until the new one is in place and restored if the
  swap fails. A log of each update is written to `update.log` in the settings folder
  (`%APPDATA%\Physiscore`, `~/Library/Application Support/Physiscore`,
  `~/.config/Physiscore`).

**Turning it off for a whole machine**: set the environment variable
`PHYSISCORE_NO_UPDATE=1`. Continuous-integration runners (`CI` set) never check
automatically.

Command line: `Physiscore --update` (or `physiscore update`) checks and, for an installed
copy, installs the latest release; `physiscore update --check-only` only reports.

**How an update is detected, step by step**

1. At start-up the program removes what a finished update left behind (the downloaded
   package, the staging folder, the previous copy).
2. If the setting is not *Off*, `PHYSISCORE_NO_UPDATE` is not set and the last check is
   more than 24 hours old, it asks GitHub three seconds after start-up for the latest
   release (`releases/latest`). *Check now* in the Updates tab asks at once.
3. The release's version is compared with the installed one (numerically: 3.10.0 is newer
   than 3.9.2). The file for this computer is chosen by operating system, processor
   (`arm64` / `x86_64`) and installation type (installer, portable, app, `.deb`, folder).
4. With *Download and install*, the file is downloaded into the settings folder
   (`updates/`), its SHA-256 is compared with `SHA256SUMS.txt`, and the new copy is
   unpacked next to the old one. The status bar and the Updates tab say so.
5. You are asked whether to restart now. Otherwise a small helper script waits until the
   program has closed, swaps the copies (or runs the installer silently), restores the old
   copy if anything fails, and writes `update.log`.
6. The first start of the new version opens its release notes (**Help → What's new**).

**The Updates tab** shows the installed version, how this copy was installed, whether it
can update itself (and why not: a read-only folder, a pip or source installation), the
setting, the time of the last check, the latest release seen and the state (*checking or
downloading*, *x.y.z is available*, *downloaded and verified - installed when you close
Physiscore*, *up to date*). *Install now and restart* appears once an update is ready;
*What's new* opens the release notes of the installed version; *Release page* opens GitHub.

**Copies older than 3.1.2 on macOS and Linux**: those builds could not verify GitHub's
certificate from inside the bundled program, so their automatic check fails. Install the
current version once by hand; from then on updates work.

## Documentation on the computer

Every installer contains the user guide, the methods and algorithms, the validation table,
the file formats, the command line and this installation guide, with all screenshots, and
the release notes of each version. They open offline in the browser from the **Help** menu
(**F1** for the user guide), from *User guide* and *Method notes* in the main window (the
latter at the selected tool's section), from the Start menu on Windows (*Physiscore user
guide*, *Physiscore methods*), from the right-click menu of the application on Linux, and
from the command line: `Physiscore --doc METHODS` or `physiscore docs METHODS --section 3.`.
The pages are written to a cache folder (`~/Library/Caches/Physiscore/docs`,
`%LOCALAPPDATA%\Physiscore\docs`, `~/.cache/physiscore/docs`).

## Checking a download

Each release has `SHA256SUMS.txt`; the same values are printed in the release notes.

```bash
shasum -a 256 Physiscore-<version>-macos-arm64.dmg            # macOS
sha256sum -c SHA256SUMS.txt --ignore-missing        # Linux
```

```powershell
Get-FileHash .\Physiscore-<version>-windows-x64-setup.exe     # Windows
```

## Building the installers yourself

The workflow [`.github/workflows/release.yml`](../.github/workflows/release.yml) builds
everything on GitHub's runners (Windows, macOS arm64, macOS Intel, Ubuntu 22.04),
runs each build's self-test, test-installs the Windows installer, the `.deb` and the
`.tar.gz`, and attaches the files to the release when a `v*` tag is pushed. *Run
workflow* on the Actions tab builds without publishing. Locally:

```bash
python -m pip install pyinstaller pillow
python packaging/make_icons.py --source logo/logo.png --out packaging/icons
pyinstaller --noconfirm packaging/physiscore.spec
packaging/macos/build_dmg.sh "Physiscore.app" Physiscore <version>     # macOS
packaging/linux/build_linux.sh <version>                     # Linux
```

On Windows install [Inno Setup 6](https://jrsoftware.org/isinfo.php) and run
`ISCC.exe /DAppVersion=<version> packaging\windows\installer.iss`.
