# Build from a clone of this repo:  makepkg -si
pkgname=kestrel-browser
pkgver=0.1.0
pkgrel=1
pkgdesc="Keyboard-driven web browser for Omarchy (Qt WebEngine)"
arch=('any')
url="https://github.com/DaCoder1/Browser"
license=('MIT')
depends=('python' 'python-pyqt6' 'python-pyqt6-webengine' 'qt6-wayland')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
optdepends=('libnotify: download notifications'
            'ttf-jetbrains-mono-nerd: default UI font')
source=()

build() {
  cd "$startdir"
  rm -rf dist
  python -m build --wheel --no-isolation
}

package() {
  cd "$startdir"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 packaging/kestrel.desktop "$pkgdir/usr/share/applications/kestrel.desktop"
  install -Dm644 packaging/kestrel.svg "$pkgdir/usr/share/icons/hicolor/scalable/apps/kestrel.svg"
  install -Dm644 config.example.toml "$pkgdir/usr/share/doc/kestrel/config.example.toml"
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
