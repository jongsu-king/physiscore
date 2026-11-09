#!/usr/bin/env bash
# Package the one-folder build into a .tar.gz (with install.sh) and a .deb.
# Usage: packaging/linux/build_linux.sh 2.1.0   (after pyinstaller, from the repository root)
set -euo pipefail
VERSION="$1"
ID=physiscore
SLUG=Physiscore
BUILD=Physiscore           # PyInstaller output folder and executable name
NAME="Physiscore"
SUMMARY="Physics-constrained analysis of thin-film solar-cell measurements"

# --- portable archive with a per-user installer
STAGE=$(mktemp -d)/$SLUG
cp -R "dist/$BUILD" "$STAGE"
for f in install.sh uninstall.sh; do
  sed -e "s|@ID@|$ID|g" -e "s|@EXE@|$BUILD|g" "packaging/linux/$f" > "$STAGE/$f"
done
cp packaging/icons/app-256.png "$STAGE/$ID.png"
sed -e "s|@NAME@|$NAME|" -e "s|@SUMMARY@|$SUMMARY|" -e "s|@ID@|$ID|" packaging/linux/app.desktop > "$STAGE/$ID.desktop"
cp LICENSE README.md "$STAGE/"
chmod +x "$STAGE/install.sh" "$STAGE/uninstall.sh"
tar -C "$(dirname "$STAGE")" -czf "dist/${SLUG}-${VERSION}-linux-x86_64.tar.gz" "$SLUG"

# --- Debian/Ubuntu package
PKG=$(mktemp -d)/${ID}_${VERSION}_amd64
mkdir -p "$PKG/DEBIAN" "$PKG/opt" "$PKG/usr/bin" "$PKG/usr/share/applications" \
         "$PKG/usr/share/icons/hicolor/256x256/apps" "$PKG/usr/share/doc/$ID"
cp -R "dist/$BUILD" "$PKG/opt/$ID"
ln -s "/opt/$ID/$BUILD" "$PKG/usr/bin/$ID"
sed -e "s|@NAME@|$NAME|" -e "s|@SUMMARY@|$SUMMARY|" -e "s|@ID@|$ID|" -e "s|@EXEC@|/opt/$ID/$BUILD|" \
    packaging/linux/app.desktop > "$PKG/usr/share/applications/$ID.desktop"
cp packaging/icons/app-256.png "$PKG/usr/share/icons/hicolor/256x256/apps/$ID.png"
cp LICENSE "$PKG/usr/share/doc/$ID/copyright"
cat > "$PKG/DEBIAN/control" <<CONTROL
Package: $ID
Version: $VERSION
Section: science
Priority: optional
Architecture: amd64
Installed-Size: $(du -sk "$PKG" | cut -f1)
Depends: libc6 (>= 2.35), libx11-6, libxft2, libxss1, libfontconfig1, libgl1, libglib2.0-0
Maintainer: Jongsu Lim <313024960+jongsu-king@users.noreply.github.com>
Homepage: https://github.com/jongsu-king/physiscore
Description: $SUMMARY
 One interface for J-V (light and dark), EQE, absorption, XRD, PL, Raman,
 FTIR, SEM and XPS: every device parameter is recomputed from the measured curve.
CONTROL
dpkg-deb --build --root-owner-group "$PKG" "dist/${ID}_${VERSION}_amd64.deb"
ls -la dist
