# LinFileCopy

A native GTK 3 + Python desktop dashboard for building, running, monitoring and
scheduling file copy and sync jobs, powered by **rsync** and **rclone**.

> **Status: design phase.** Nothing is implemented yet. The technical concept and
> mockups are up for review.

- [Technical concept](docs/CONCEPT.md): architecture, build order, feature → flag mapping, icon map
- [Mockups](docs/mockups/index.html): open locally in a browser (self-contained, works offline)
- [Icon manifest](tools/icons.manifest): every icon the app uses, from the local Phosphor set

## Rebuilding the mockups

```sh
python3 tools/build_mockups.py            # uses $LFC_ICON_SRC or the default asset path
```

## Licence

Icons: [Phosphor Icons](https://phosphoricons.com) v2.0.8, MIT.
