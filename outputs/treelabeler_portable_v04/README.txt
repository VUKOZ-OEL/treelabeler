=====================================================
  TreeLabeler — standalone portable verze 04
=====================================================

OBSAH BALICKI
  treelabeler.exe — samotna aplikace.  run_example.bat — příklad spuštění.

POUŽITÍ
  1. Spusť treelabeler.exe — otevře se GUI na http://127.0.0.1:8000.
  2. Zadej cestu ke složce s LAS/LAZ soubory, klikni **Load**.
  3. Labely klávesami: Q/W/E = species, A/S/D/F = segmentation.
     Space = přeskoč na další strom. C = kontext okolních stromů (show/hide).

NOVÉ OPROTI v03:
  - **Progress bar během Loadu** — velký pás v headeru ukazuje
    `current/total: filename` a progress; po načtení se vrátí původní
    rozložení. Funguje na velkých složkách (tisíce souborů).
  - **Async scan** — složky s >30 soubory se skenují ve vlákně, UI zůstává
    interaktivní.
  - **DB reuse** — znovuotevření projektu se drží existující `*.db`
    (nestvoří se nová shadow databáze).
  - **Tree relocation** — pokud se LAZ soubor přesune, jeho subtree id je
    nadšeně UPDATE (bez IntegrityError).
  - **Filename-agnostic context** — okolní mračna se hledají podle tree_id,
    ne podle prefixu `cloud_segmented_` (funguje i `tree_X.laz`).

KONTROLA
  - 26 automatických testů prochází.
  - Live test na 1 893 souborech (rn_3_trees): banner + progress běží,
    po scanu se GUI vrátí do původního stavu.
