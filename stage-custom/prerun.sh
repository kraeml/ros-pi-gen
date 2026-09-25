#!/bin/bash -e
# stage-custom hängt als zusätzliche Stage in der STAGE_LIST hinter pi-gens
# stage2 (stage0 stage1 stage2 stage-custom): dieses prerun übernimmt das
# fertige RootFS von stage2 (copy_previous) — auf dem wird nur noch 05–07
# ausgeführt und aus diesem Stage exportiert (EXPORT_IMAGE in diesem Dir).
# pi-gens stage2 exportiert nicht, weil make setup dort SKIP_IMAGES setzt
# (in pi-gens .gitignore enthalten — der Submodul-Status bleibt sauber).

if [ ! -d "${ROOTFS_DIR}" ]; then
	copy_previous
fi
