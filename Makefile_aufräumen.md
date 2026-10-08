Dein Eindruck stimmt zum Teil. Das Makefile ist nicht komplizierter als nötig, aber es vermischt drei Aufgaben, und ein Teil davon dupliziert, was pi-gen selbst kann. Ich trenne das, weil nur ein Teil davon wirklich Ballast ist.

## Was das Makefile tatsächlich tut

Es hat vier Aufgabenblöcke:

| Block | Targets | Zeilen (grob) |
|---|---|---|
| Image bauen | `setup`, `build`, `apply-variant`, `clean-*`, Guards | ~120 |
| Testen/Linten | `venv`, `lint`, `test` | ~20 |
| Release/Publish | `package*`, `publish-s3-*`, `release*` | ~70 |
| VM-Build | `vm-*` | ~60 |

Der Block „Image bauen" ist der, um den es bei deiner pi-gen-Frage geht. Die anderen drei sind eigene Themen.

## Wo pi-gen schon etwas mitbringt, das du nachbaust

**1. Varianten über `SKIP`-Dateien.** `apply-variant` legt in `06-variant-*` eine `SKIP`-Datei an oder löscht sie. Das ist tatsächlich ein pi-gen-Mechanismus (SKIP in Stage- und Sub-Stage-Verzeichnissen), du nutzt ihn also schon. Der Teil ist idiomatisch. Unschön ist nur, dass das Makefile dafür Dateien in einem versionierten Verzeichnis anlegt und löscht (`$(STAGE_DIR)/.../SKIP`). Dadurch wird der Arbeitsbaum je nach Zustand dirty. Der Docker-Weg mountet `stage-custom` zudem read-only (`:ro`), das SKIP muss also vor dem Start gesetzt sein. Das ist konsistent, nur fehleranfällig.

**2. Stage-Auswahl über `STAGE_LIST`.** pi-gen bietet `STAGE_LIST` in der `config`. Das nutzt du im Native-Zweig, im Docker-Zweig steht es vermutlich in `config`. Der `MODE=overlay`-Zweig mit `sed` über die `config` ist dagegen ein Umweg, den pi-gen nicht braucht. Das Makefile sagt selbst „Legacy". Er ist der erste Kandidat zum Streichen.

**3. `SKIP_IMAGES`.** Du schreibst `SKIP_IMAGES` per `touch` in Stage-Verzeichnisse. Das ist wieder der pi-gen-Mechanismus, korrekt genutzt.

**4. `CONTINUE=1` und `PRESERVE_CONTAINER`.** Auch das sind Optionen von `build-docker.sh`, die du durchreichst. Richtig.

**5. `CLEAN=1`.** Gleiches.

Du nutzt also mehr von pi-gen, als dein Eindruck vermuten lässt. Nachgebaut ist vor allem Folgendes:

- **`pi-gen/config` löschen** (`rm -f $(PIGEN_DIR)/config`) und die Stale-Overlay-Erkennung. Das ist ein Pflaster für den Overlay-Modus. Ohne Overlay-Modus entfällt das Problem.
- **`guard-pigen` mit Commit-Vergleich.** Das macht ein Submodul bereits: `git submodule status` zeigt Abweichungen. Der Guard prüft gegen eine zweite Wahrheit (`PIGEN_COMMIT` im Makefile). Hier gibt es zwei Quellen für denselben Pin (Submodul-Eintrag im Git-Index und die Variable). Eine davon ist überflüssig.
- **`binfmt-*`.** Eigene Logik, die pi-gens Docker-Build mit QEMU-Besonderheiten ergänzt. Das ist keine Doppelung, sondern ein echtes Problem von arm64-Emulation, das pi-gen nicht löst.

## Was ich vereinfachen würde

In dieser Reihenfolge, nach Nutzen pro Aufwand:

1. **`MODE=overlay` streichen.** Das entfernt den `sed`-Zweig, `guard`-Pflaster für `pi-gen/config` und `PIGEN_VARIANT`-Anhängen. Rund 25 Zeilen und eine ganze Fehlerklasse, wenn niemand den Modus nutzt. Prüf, ob Tests ihn noch brauchen (`tests/test_overlay_files.py` heißt schon danach).
2. **Release-/Publish-Block auslagern.** Diese ~70 Zeilen sind keine Build-Logik. Sie gehören in ein zweites Makefile (`release.mk`, per `include`) oder direkt in `tools/release.py` mit Unterbefehlen. Die Targets sind ohnehin dünne Wrapper um Python-Skripte, bei denen die Argumentzusammenstellung in Make deutlich schwerer zu lesen ist als in Python. Besonders `release-preflight` mit der Shell-Array-Konstruktion in einer Make-Rezeptzeile ist ein Kandidat.
3. **VM-Block auslagern.** Ebenfalls eigene Datei (`vm.mk`). Er hat keinen Bezug zum normalen Build und stört beim Lesen.
4. **Variablen-Dopplung beim Pin entfernen.** Eine Quelle für den pi-gen-Commit, entweder das Submodul oder `PIGEN_COMMIT`. Wenn du den Guard behalten willst, lies den Soll-Commit aus `.gitmodules`/dem Index statt ihn zu wiederholen.
5. **Die SKIP-Dateien nicht im Quellbaum verwalten.** Statt `touch`/`rm` im Repo (`04-user-data/SKIP`, `06-variant-*/SKIP`) könntest du die Auswahl über `STAGE_LIST` und eine kleine, pro Build erzeugte Stage-Kopie in `work/` steuern. Das ist aber ein größerer Umbau, und das aktuelle Vorgehen funktioniert. Ich würde das nur angehen, wenn dich der dirty Arbeitsbaum stört.

Nach 1 bis 3 bleibt ein Makefile von etwa 150 Zeilen, das nur noch `setup`, `build`, `test`, `lint` und `clean-*` enthält. Das ist überschaubar.

## Was ich nicht anfassen würde

- **Die Guards `guard-container` und `guard-variant`.** Sie verhindern teure Fehlläufe (ein Image-Build dauert lange), und die Fehlermeldungen sind hilfreich.
- **`RELEASE_BUILD=1` als Default.** Das ist eine bewusste Sicherheitsentscheidung, damit Testbenutzer nicht versehentlich in ein Release gelangen. Die Begründung steht im Kommentar. Lass es.
- **Den Thin-Wrapper-Ansatz.** Dass CI dieselben Targets wie lokal aufruft, ist sinnvoll.

## Was ich nicht beurteilen kann

Ich sehe `tools/build-docker.sh`, `config` und die Stage-Skripte nicht. Wenn dort Logik steckt, die Make dupliziert (zum Beispiel das Setzen von `STAGE_LIST` oder `WORK_DIR`), fällt das erst beim Lesen dieser Dateien auf. Der native Zweig setzt `STAGE_LIST` und `WORK_DIR` direkt im Makefile, der Docker-Zweig vermutlich in `config`: Das wären zwei Stellen für dieselbe Information. Schick mir `config` und `tools/build-docker.sh`, dann sage ich dir, ob sich das zusammenführen lässt.

Zur Einordnung: Das Makefile wirkt kompliziert, weil es mehrere Aufgaben trägt, nicht weil der Build-Teil zu verwickelt wäre. Wenn du erst Overlay streichst und die Release- und VM-Blöcke auslagerst, löst sich der Großteil des Gefühls auf, ohne dass du pi-gens Mechanismen anders nutzen müsstest.
