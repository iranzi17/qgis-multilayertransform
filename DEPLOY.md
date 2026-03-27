# Deployment

## Share As ZIP

1. Give users the plugin ZIP file.
2. In QGIS, they open `Plugins > Manage and Install Plugins... > Install from ZIP`.
3. They select the ZIP and install it.

## Install By Folder

1. Copy the `MultiLayerTransform` folder into the QGIS profile plugin directory.
2. Restart QGIS.
3. Enable the plugin from the plugin manager.

Typical Windows plugin folder:

```text
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
```

## Updating An Existing Installed Copy

Use the workspace script:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\sync-installed-plugin.ps1
```

The script:

- checks whether QGIS is running
- creates a timestamped backup
- updates the installed plugin safely from the source folder

## Public Distribution

For direct sharing, the ZIP file is enough.

For wider public use, submit the plugin package to the QGIS plugin repository.

## QGIS Plugin Repository

1. Prepare one release ZIP with the plugin folder at the archive root.
2. Confirm `metadata.txt` is complete and accurate.
3. Make sure the package includes a license file.
4. Sign in with your OSGeo account at `https://plugins.qgis.org/plugins/add/`.
5. Upload the ZIP and submit it for review.
6. Wait for repository approval before the plugin becomes publicly available.

### Submission Checklist

- `author` is correct
- `email` is filled
- `homepage` is filled
- `repository` is filled
- `tracker` is filled
- `icon` points to a packaged web image
- `LICENSE` file is included in the ZIP
- version number is correct
