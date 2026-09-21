=====================================================
  TreeLabeler — standalone portable verze 03
=====================================================

OBSAH BALICKI
  treelabeler.exe          — samotna aplikace. Stačí zkopírovat na cílový PC a spustit.
                             Nic jiného nepotřebuje (žádný python, žádný config).
  run_example.bat           — příklad spuštění (uprav cestu ke své složce s LAZ).

POUŽITÍ
  1. Nakopíruj `treelabeler.exe` na CLI PC.
  2. Spusť ho — objeví se prázdné GUI (bez dat).
  3. Do pole vlevo nahoře zadej cestu ke složce s LAS/LAZ soubory
     (např. `D:\moje_data\projekt1`), stiskni **Load**.
  4. Zvol kategorie (Q/W/E + A/S/D/F), Space = přeskok na další strom.

NOVÉ OPROTI v02:
  - **Filenames s libovolným prefixem** — tree_Y.laz, strom_07.laz, atd. — se
    správně rozpoznají a labelují (fix contextu: soubor se hledá podle tree_id,
    ne podle hardcoded cloud_segmented_ prefixu).
  - Background soubor se hledá jako `*-1.laz` (cloud_segmented_-1.laz
    i tree_-1.laz fungují).
  - Funguje i bez sqlite (pokud tabulku trees neexistuje, použije se vlastní
    `.db` vytvořená treelabelerem).

NOVÉ OPROTI v01:
  - 3×3 m měřtková mřížka pod stromem z dist2dmt ze sqlite
  - Kontext okolních stromů na `C` nebo tlačítko **Context** — sousedi
    (olivové) + pozadí (šedá) z -1 souboru, ořez target bbox +1 m
  - Auto-skip mimo analýzu pro `cloud_segmented_-1.laz`
  - Persistentní labely v cizí writable sqlite (files/labels/categories vedle
    trees); fallback `.labels.sqlite` na read-only / source_data režim

KONTROLA
  - Aplikace startuje `http://127.0.0.1:8000`.
  - C = show/hide kontextu, Space = Next.
  - 26 automatických testů prochází.
