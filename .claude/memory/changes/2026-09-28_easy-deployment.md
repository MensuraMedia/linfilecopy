---
date: 2026-09-28
type: feature
files_changed: [get.sh, tools/build_release.sh, tools/build_deb.sh, releases/linfilecopy-0.1.0.tar.gz, releases/linfilecopy_0.1.0-1_all.deb, releases/SHA256SUMS, releases/README.md, README.md, changelog.md]
---

## Change: one-line GitHub installer and a universal release tarball
- `get.sh` downloads from raw.githubusercontent.com/…/<LFC_REF>/releases, checks each file against
  SHA256SUMS before use, then installs the .deb with apt (apt systems) or unpacks the tarball and
  runs `install.sh --user` (any distro). `--deb`, `--user`, `--uninstall`; curl or wget.
- `tools/build_release.sh` builds the .deb (via build_deb.sh) and a reproducible `git archive`
  tarball of the runtime files, then writes SHA256SUMS for both.
- No GitHub Releases: `gh` is not authenticated here, so release files live in `releases/` on main.
## Notes
- The .deb is chmod 644 in a 755 temp dir so apt's `_apt` sandbox user can read it.
- SHA256SUMS comes from the same host, so it protects against corrupt/partial downloads, not a
  compromised repository.
## Testing
get.sh --user and --uninstall in a throw-away HOME against a local file:// release folder, and
against the pushed GitHub URLs.
