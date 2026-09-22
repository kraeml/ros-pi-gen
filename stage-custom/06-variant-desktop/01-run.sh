#!/bin/bash -e
# Desktop-Variante: LightDM bedingungslos aktivieren — die Existenz dieser
# Sub-Stage ist der Varianten-Schalter (make VARIANT=desktop entfernt das
# SKIP dieser Sub-Stage und setzt eines für 06-variant-headless; siehe
# Makefile / README, „Variante wählen").
# Bewusst NICHT "VARIANT" als Variablenname: console-setup (setupcon) nutzt
# dieselbe Variable im Chroot und scheitert sonst an fehlenden
# keyboard.headless-Konfigen.

on_chroot << EOF
systemctl enable lightdm.service
EOF
