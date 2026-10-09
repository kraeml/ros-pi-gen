#!/bin/bash -e
install -m 755 files/doitpi_firstboot.sh \
  "${ROOTFS_DIR}/usr/local/sbin/doitpi_firstboot.sh"
install -m 644 files/doitpi_firstboot.service \
  "${ROOTFS_DIR}/etc/systemd/system/doitpi_firstboot.service"
install -m 755 files/50-doitpi \
  "${ROOTFS_DIR}/etc/update-motd.d/50-doitpi"

on_chroot << EOF
systemctl enable doitpi_firstboot.service
EOF
