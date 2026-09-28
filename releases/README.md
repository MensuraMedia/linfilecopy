# Releases

| File | What it is |
|---|---|
| `linfilecopy_0.1.0-1_all.deb` | Debian/Ubuntu/Mint package (architecture-independent), built with `tools/build_deb.sh` |
| `linfilecopy-0.1.0.tar.gz` | Universal tarball for any distribution: unpack and run `./install.sh --user` |
| `SHA256SUMS` | Checksums of both files, verified by `install.sh` and `get.sh` |

Quickest way, straight from GitHub:

```sh
curl -fsSL https://raw.githubusercontent.com/MensuraMedia/linfilecopy/main/get.sh | sh               # .deb with apt
curl -fsSL https://raw.githubusercontent.com/MensuraMedia/linfilecopy/main/get.sh | sh -s -- --user  # any distro, no root
```

By hand (Debian, Ubuntu and derivatives):

```sh
sha256sum -c SHA256SUMS
sudo apt install ./linfilecopy_0.1.0-1_all.deb
```

By hand (any distribution, no root):

```sh
sha256sum -c SHA256SUMS
tar -xzf linfilecopy-0.1.0.tar.gz
cd linfilecopy-0.1.0 && ./install.sh --user
```

From a clone, `./install.sh` verifies the checksum and installs the package with apt;
`./install.sh --user` installs for your user on any distribution.

To rebuild after changing the code: commit, then `tools/build_release.sh` (the .deb needs
`debhelper dh-python pybuild-plugin-pyproject python3-all`; the build runs the full test suite).
Both files are built from `HEAD`, and the tarball is reproducible (`git archive`).
