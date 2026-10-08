#!/bin/bash -e
install -m 755 files/doitpi_firstboot.sh \
  "${ROOTFS_DIR}/usr/local/sbin/doitpi_firstboot.sh"
install -m 644 files/doitpi_firstboot.service \
  "${ROOTFS_DIR}/etc/systemd/system/doitpi_firstboot.service"

on_chroot << EOF
systemctl enable doitpi_firstboot.service
EOF
