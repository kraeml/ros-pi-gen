# Thin-Wrapper für den Image-Build (pi-gen) und die Testinfra.
# Alle Logik liegt in versionierten Targets/Skripten im Repo — GitHub-Actions
# ruft ausschließlich diese auf (Thin-Wrapper-Prinzip, siehe
# GitHub-Image-Workflow.md, § 2). Identisch lokal lauffähig.
#
# Wichtigste Aufrufe:
#   make setup && make build          # Docker-Build (Default), headless
#   make build VARIANT=desktop        # Desktop-Variante
#   make build ENGINE=native          # nativer Build ohne Docker
#   make setup MODE=overlay           # Legacy: Overlay-cp in pi-gen/stage2
#   make test                         # Testinfra (Gruppe Q) gegen deploy/
#   make ci                           # venv lint setup build test
#
# Variablen (über Env oder Kommandozeile): MODE, VARIANT, ENGINE,
# CONTINUE, PRESERVE_CONTAINER, CLEAN, SKIP_IMAGES_BUILD
# (letzte: pi-gens SKIP_IMAGES-Mechanismus für schnelleren Iterationslauf,
# siehe README, „Entwicklung: schnelle Iteration“).

SHELL := /bin/bash

# --- Pfade -----------------------------------------------------------------
REPO_ROOT  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
STAGE_DIR  := $(REPO_ROOT)/stage-custom
PIGEN_DIR  := $(REPO_ROOT)/pi-gen
WORK_DIR   := $(REPO_ROOT)/work
DEPLOY_DIR := $(REPO_ROOT)/deploy
VENV       := $(REPO_ROOT)/.venv

# --- Optionen ---------------------------------------------------------------
MODE     ?= stage-custom
VARIANT  ?= headless
ENGINE   ?= docker

# --- VM-Build (robotics-lab-vm-Submodul, Details: README „Build in der VM") --
# Ubuntu 24.04 in VirtualBox: qemu-user-static 8.x emuliert OFD korrekt —
# das binfmt Version-Gate überspringt dort den Entry komplett (kein
# Kernel-Eingriff). Das Repo landet per vm-sync auf der VM-Disk (nicht im
# geteilten Ordner — vboxsf ist für Builds deutlich zu langsam).
VAGRANT_DIR := $(REPO_ROOT)/vm/robotics-lab-vm
VM_DISK     ?= 80GB           # einmalig beim ersten vm-up; später ändern = vm-destroy
VM_USER     ?= vagrant
VM_IP      ?= 192.168.33.11  # Host-Only-IP der VM (Submodul-ENV VM_IP, Default .10) — .10 durch die laufende pi-gen-Dev-VM belegt
VM_SSH_OPTS := -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
VM_DEST     := build/ros-pi-gen
VM_NAME     ?= ros-pi-gen     # VirtualBox-Name; Default im Submodul-Vagrantfile: robotics

PIGEN_COMMIT    := 74d08a3
VARIANT_STAGES  := 06-variant-headless 06-variant-desktop

# build-docker.sh: Deploy landet via `docker cp` im cwd des Aufrufs —
# daher aus dem Repo-Root aufrufen, dann liegt deploy/ in ros-pi-gen/deploy.
PIGEN_DOCKER_OPTS := --volume $(STAGE_DIR):/pi-gen/stage-custom:ro \
                     --volume $(WORK_DIR):/pi-gen/work

# shellcheck-Dateisatz: build- und setup-Skripte der Stage + Wrapper.
# Nicht gescannt: config (sourced von pi-gen mit set -u; die Variablen sind
# pi-gen-seitig belegt — SC2034/SC2148-Mehrheit) und die vendor'ten
# AccessPopup-Skripte (unverändert, siehe
# stage-custom/07-accesspopup/files/VENDORED.md).
SHELL_FILES := $(shell find $(STAGE_DIR) -maxdepth 2 -name '*-run.sh' 2>/dev/null | sort) \
               $(STAGE_DIR)/prerun.sh \
               $(REPO_ROOT)/tools/binfmt.sh \
               $(REPO_ROOT)/tools/build-docker.sh

.DEFAULT_GOAL := help
.PHONY: help venv lint setup build test ci clean-variant-skips clean-container clean-work
.PHONY: binfmt-setup binfmt-cleanup
.PHONY: setup-stage-custom setup-overlay
.PHONY: guard-vagrant vm-up vm-ssh vm-status vm-bootstrap vm-sync vm-build vm-test
.PHONY: vm-artifacts vm-halt vm-destroy vm-ci

help:
	@echo "ros-pi-gen — Thin-Wrapper (Details: README.md, GitHub-Image-Workflow.md)"
	@echo
	@echo "  make venv                     venv + Testabhängigkeiten anlegen"
	@echo "  make lint                     shellcheck (Stage + Wrapper) + Overlay-Tests"
	@echo "  make setup                    pi-gen vorbereiten (MODE=stage-custom|overlay, VARIANT=…)"
	@echo "  make build                    Image bauen (ENGINE=docker|native, VARIANT=…)"
	@echo "  make test                     Testinfra (Gruppe Q) gegen das Image in deploy/"
	@echo "  make ci                       venv lint setup build test"
	@echo "  make clean-container          verwaisten Build-Container pigen_work entfernen"
	@echo "  make clean-work               partielles/persistentes work/ entfernen (Bootstrap frisch)"
	@echo "  make binfmt-setup|cleanup     qemu-Emulation-Entry (Container-qemu, F-Flag) setzen/entfernen"
	@echo
	@echo "  VM (robotics-lab-vm, Ubuntu 24.04 — qemu 8.x, kein binfmt-Eingriff):"
	@echo "  make vm-up|vm-ssh|vm-status   VM starten / betreten / Status"
	@echo "  make vm-bootstrap|vm-sync     VM vorbereiten / Repo übertragen (~5 MB)"
	@echo "  make vm-build|vm-test         Build/Test in der VM (VARIANT/CONTINUE fließen durch)"
	@echo "  make vm-artifacts             deploy/ aus der VM holen (nach deploy/vm/)"
	@echo "  make vm-halt|vm-destroy       VM anhalten / löschen · make vm-ci = ganze Kette"
	@echo
	@echo "Variablen: MODE=$(MODE) VARIANT=$(VARIANT) ENGINE=$(ENGINE) CONTINUE=$(CONTINUE) PRESERVE_CONTAINER=$(PRESERVE_CONTAINER) CLEAN=$(CLEAN) VM_DISK=$(VM_DISK) VM_NAME=$(VM_NAME) VM_IP=$(VM_IP)"

# --- venv (Datei-Abhängigkeit: requirements ändern sich -> neu installieren)
$(VENV)/bin/python: tests/requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r tests/requirements.txt
	touch $@

venv: $(VENV)/bin/python

# --- lint -------------------------------------------------------------------
lint: venv guard-pigen
	@shellcheck $(SHELL_FILES)
	$(VENV)/bin/python -m pytest tests/test_overlay_files.py tests/test_hostname_ssid.py -q

# --- setup ------------------------------------------------------------------
# Entfernt Overlay-Reste aus pi-gen (Rückstände eines MODE=overlay-Laufs
# würden in stage-custom sonst doppelt/falsch ausgeführt). KRITISCH ist
# pi-gen/config: build.sh sourced es im Container VOR -c /config — ein
# Stale-Overlay-Stand (STAGE_LIST ohne stage-custom) würde über den
# ${STAGE_LIST:-…}-Soft-Default der Repo-Config gewinnen, stage-custom
# lief nie (stummer Fehlschlag, Beleg: Build-Log 2026-09-23). Die config
# ist in pi-gen gitignored — der Submodul-Status zeigt sie nicht an.
setup: guard-pigen clean-variant-skips
ifeq ($(MODE),stage-custom)
	@rm -f $(PIGEN_DIR)/stage2/SKIP_IMAGES
	@touch $(PIGEN_DIR)/stage2/SKIP_IMAGES
	@rm -rf $(PIGEN_DIR)/stage2/05-docker-ansible $(PIGEN_DIR)/stage2/06-variant* $(PIGEN_DIR)/stage2/07-accesspopup
	@rm -f $(PIGEN_DIR)/config
	@test ! -f $(PIGEN_DIR)/config || { echo "pi-gen/config ließ sich nicht entfernen — Stale-Overlay-Stand würde stage-custom verschatten" >&2; exit 1; }
	@$(MAKE) --no-print-directory apply-variant
	@echo "setup: MODE=stage-custom — pi-gen @ $$(git -C $(PIGEN_DIR) rev-parse --short HEAD), stage2 exportiert nicht, stage-custom exportiert ($(VARIANT))"
else ifeq ($(MODE),overlay)
	@rm -f $(PIGEN_DIR)/stage2/SKIP_IMAGES
	@cp -r $(STAGE_DIR)/05-docker-ansible $(STAGE_DIR)/07-accesspopup $(PIGEN_DIR)/stage2/
	@rm -rf $(PIGEN_DIR)/stage2/06-variant-headless $(PIGEN_DIR)/stage2/06-variant-desktop
	@cp -r $(STAGE_DIR)/06-variant-$(VARIANT) $(PIGEN_DIR)/stage2/06-variant
	@sed -e 's@^export STAGE_LIST=.*@export STAGE_LIST="$${BASE_DIR}/stage0 $${BASE_DIR}/stage1 $${BASE_DIR}/stage2"@' \
	     -e '/^# Variante headless\/desktop wird nicht mehr hier gesetzt/,+2d' \
	     -e '/^# Bewusst NICHT "VARIANT"/,+6d' \
	     $(REPO_ROOT)/config > $(PIGEN_DIR)/config
	@printf "\nexport PIGEN_VARIANT='%s'\n" "$(VARIANT)" >> $(PIGEN_DIR)/config
	@echo "setup: MODE=overlay — Overlay nach pi-gen/stage2 kopiert (pi-gen-Tree dirty, Legacy-Weg; Variante $(VARIANT))"
else
	$(error Unbekannter MODE=$(MODE) — stage-custom oder overlay)
endif

# Sub-Stage-SKIPs je Variante: die existierende Sub-Stage ist der Schalter.
apply-variant:
	@test "$(VARIANT)" = "headless" -o "$(VARIANT)" = "desktop" || { echo "Unbekannter VARIANT=$(VARIANT) (headless|desktop)" >&2; exit 1; }
	@for s in $(VARIANT_STAGES); do \
		if [ "$$s" = "06-variant-$(VARIANT)" ]; then rm -f $(STAGE_DIR)/$$s/SKIP; else touch $(STAGE_DIR)/$$s/SKIP; fi; \
	done

clean-variant-skips:
	@rm -f $(foreach s,$(VARIANT_STAGES),$(STAGE_DIR)/$(s)/SKIP)

# --- build ------------------------------------------------------------------
# Docker-Weg: tools/build-docker.sh orchestriert binfmt-Entry (Version-Gate:
# moderner Host-Interpreter -> kein Kernel-Eingriff) + trap-gesichertes
# Cleanup (Ctrl+C inklusive) um build-docker.sh.
build: guard-pigen guard-variant guard-container
ifeq ($(ENGINE),docker)
	@mkdir -p $(WORK_DIR) $(DEPLOY_DIR)
	@CONTINUE=$(CONTINUE) PRESERVE_CONTAINER=$(PRESERVE_CONTAINER) \
	  PIGEN_DOCKER_OPTS='$(PIGEN_DOCKER_OPTS)' \
	  tools/build-docker.sh
else ifeq ($(ENGINE),native)
	cd $(PIGEN_DIR) && sudo env \
	  STAGE_LIST="$(PIGEN_DIR)/stage0 $(PIGEN_DIR)/stage1 $(PIGEN_DIR)/stage2 $(STAGE_DIR)" \
	  WORK_DIR=$(WORK_DIR)/'$(shell source $(REPO_ROOT)/config && echo $${IMG_NAME})' \
	  DEPLOY_DIR=$(DEPLOY_DIR) \
	  CLEAN=$(CLEAN) \
	  ./build.sh -c $(REPO_ROOT)/config
else
	$(error Unbekannter ENGINE=$(ENGINE) — docker oder native)
endif

# --- test -------------------------------------------------------------------
test: venv
	$(VENV)/bin/python -m pytest tests $(TEST_ARGS)

# --- ci (Pipeline-Kette; Stufen wie GitHub-Image-Workflow.md, § 3) ----------
ci: venv lint setup build test

# --- Guards -----------------------------------------------------------------
guard-pigen:
	@test -e $(PIGEN_DIR)/.git || { echo "pi-gen-Submodul fehlt: git submodule update --init" >&2; exit 1; }
	@test "$$(git -C $(PIGEN_DIR) rev-parse HEAD 2>/dev/null)" = "$$(git -C $(PIGEN_DIR) rev-parse $(PIGEN_COMMIT) 2>/dev/null)" || { echo "pi-gen @ $$(git -C $(PIGEN_DIR) rev-parse --short HEAD 2>/dev/null) != gepinnt $(PIGEN_COMMIT) — git -C pi-gen checkout $(PIGEN_COMMIT)" >&2; exit 1; }

guard-variant:
	@test -f $(STAGE_DIR)/06-variant-$(VARIANT)/00-packages || { echo "VARIANT=$(VARIANT) hat kein 06-variant-$(VARIANT)/00-packages" >&2; exit 1; }

#Nicht laufende Container von früheren Läufen (exited/created) blockieren
#build-docker.sh (Abbruch "CONTINUE=1"); ein Weiterbauen würde deren alte
#Mounts/Stand erben. Läuft der Container, bricht build-docker.sh selbst ab.
guard-container:
	@if [ "$(CONTINUE)" != "1" ] && command -v docker >/dev/null 2>&1; then \
		state=$$(docker ps -a --format '{{.Names}} {{.State}}' 2>/dev/null | awk '$$1=="pigen_work"{print $$2}'); \
		if [ -n "$$state" ] && [ "$$state" != "running" ]; then \
			echo "Container pigen_work vorhanden (Zustand: $$state) — räumen: make clean-container" >&2; \
			echo "(Weiterbauen im Container: make build CONTINUE=1 — erbt dessen alte Mounts/Stand!)" >&2; \
			exit 1; \
		fi; \
	fi

# Verwaisten Build-Container entfernen (idempotent; -v löscht mitgekommene
# anonyme Volumes, bind-Mounts auf dem Host bleiben unberührt)
clean-container:
	@docker rm -v pigen_work 2>/dev/null && echo "Container pigen_work entfernt." || echo "Kein Container pigen_work vorhanden."

# Partialles Bootstrap-RootFS (z. B. nach abgebrochenem Lauf) entfernen —
# sonst überspringt stage0/prerun.sh den Bootstrap und der Build scheitert
# später im unvollständigen rootfs (README-Troubleshooting). Die Dateien
# gehören root (Build läuft im Container als root): erst normal rm, dann
# per Container (pi-gen-Image, Repo-Root gemountet — work ist dort kein
# Mountpoint), zuletzt sudo als Fallback.
clean-work:
	@rm -rf $(WORK_DIR) 2>/dev/null || \
	  docker run --rm --volume $(REPO_ROOT):/repo pi-gen rm -rf /repo/work 2>/dev/null || \
	  sudo rm -rf $(WORK_DIR)
	@echo "work/ entfernt (Bootstrap baut frisch)."

# qemu-Emulation-Entry (Container-qemu, F-Flag) — für den Docker-Build
# automatisch gesetzt/entfernt; Standalone für manuelle/containerlose Läufe
# (Details: tools/binfmt.sh-Kopf)
binfmt-setup:
	@tools/binfmt.sh setup

binfmt-cleanup:
	@tools/binfmt.sh cleanup

# --- VM (robotics-lab-vm-Submodul) ------------------------------------------
# Build in der Ubuntu-24.04-VM: Container-qemu-Entry wird vom Version-Gate
# übersprungen (VM-qemu 8.x emuliert OFD korrekt) — der VM-Kernel bleibt
# unangetastet. Repo-Transfer per rsync auf die VM-Disk (vboxsf zu langsam
# für Builds). ssh-Zugang: passwortlos via vagrant-Key (aus ssh-config).
guard-vagrant:
	@test -e $(VAGRANT_DIR)/.git || { echo "vm/robotics-lab-vm fehlt: git submodule update --init vm/robotics-lab-vm" >&2; exit 1; }
	@command -v vagrant >/dev/null || { echo "vagrant nicht installiert" >&2; exit 1; }
	@command -v rsync >/dev/null || { echo "rsync nicht installiert" >&2; exit 1; }

vm-up: guard-vagrant
	cd $(VAGRANT_DIR) && DISK_SIZE=$(VM_DISK) VM_NAME=$(VM_NAME) VM_IP=$(VM_IP) vagrant up

vm-ssh: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant ssh

vm-status: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant status

# Bootstrap: Build-Abhängigkeiten (idempotent). Die Box 26.09.11 bringt
# Docker CE + qemu-user-static bereits mit (Quelle: ../Ubuntu-Vagrant-
# Box-Build) — der Check bestätigt und greift nur bei Lücken ein.
vm-bootstrap: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant ssh -c 'set -e; \
	  for p in rsync p7zip-full e2fsprogs python3-venv qemu-user-static binfmt-support; do \
	    dpkg -s $$p >/dev/null 2>&1 || sudo apt-get install -y -qq $$p; \
	  done; \
	  if ! docker ps >/dev/null 2>&1; then \
	    echo "vm-bootstrap: Docker fehlt/unerreichbar — installiere …"; \
	    curl -fsSL https://get.docker.com | sudo sh; \
	    sudo usermod -aG docker $$USER; \
	    echo "vm-bootstrap: SSH-Session neu öffnen (docker-Gruppe greift erst dann)."; \
	  else \
	    echo "vm-bootstrap: Docker + qemu-user-static ok — bereit."; \
	  fi'

vm-sync: guard-vagrant
	@sshcfg=$$(mktemp); \
	  cd $(VAGRANT_DIR) && vagrant ssh-config > $$sshcfg; \
	  key=$$(awk '/[[:space:]]*IdentityFile/{print $$2}' $$sshcfg | tail -1); \
	  port=$$(awk '/[[:space:]]*Port[ \t]/{print $$2}' $$sshcfg | tail -1); \
	  host=$$(awk '/[[:space:]]*HostName/{print $$2}' $$sshcfg | tail -1); \
	  rm -f $$sshcfg; \
	  vagrant ssh -c 'mkdir -p $(VM_DEST)' >/dev/null; \
	  rsync -a --delete \
	    --exclude work/ --exclude deploy/ --exclude .venv/ \
	    --exclude tests/.work/ --exclude .opencode/ --exclude vm/ \
	    -e "ssh -p $$port -i $$key $(VM_SSH_OPTS)" \
	    $(REPO_ROOT)/ $(VM_USER)@$$host:$(VM_DEST)/
	@echo "vm-sync: Repo nach $(VM_DEST) synchronisiert."

vm-build: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant ssh -c 'set -e; cd $(VM_DEST); \
	  make setup VARIANT=$(VARIANT) && make build VARIANT=$(VARIANT) CONTINUE=$(CONTINUE)'

vm-test: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant ssh -c 'set -e; cd $(VM_DEST); make test'

vm-artifacts: guard-vagrant
	@mkdir -p $(DEPLOY_DIR)/vm
	cd $(VAGRANT_DIR) && vagrant ssh -c 'tar -C $(VM_DEST)/deploy -czf - .' | tar -xzf - -C $(DEPLOY_DIR)/vm
	@echo "vm-artifacts: deploy/vm/ befüllt (Image + Logs)."

vm-halt: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant halt

vm-destroy: guard-vagrant
	cd $(VAGRANT_DIR) && vagrant destroy -f

vm-ci: vm-up vm-bootstrap vm-sync vm-build vm-test
	@echo "vm-ci: Kette abgeschlossen (Artefakte: make vm-artifacts)."
