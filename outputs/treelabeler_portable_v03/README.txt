=====================================================
  TreeLabeler — standalone portable verze 03
=====================================================

OBSAH BALICKI
  treelabeler.exe          — samotna aplikace; nakopíruj a spusť, nic víc nepotřebuje.
  run_example.bat           — příklad spuštění.

POUŽITÍ
  1. Spusť treelabeler.exe — otevře se GUI na http://127.0.0.1:8000.
  2. Zadej cestu ke složce s LAS/LAZ soubory, klikni **Load**.
  3. Labely zadávej klávesami: Q/W/E = species, A/S/D/F = segmentation.
  4. Space = přeskoč na další strom. C = zobraz/skrýt okolní body.

NOVÉ OPROTI v02:
  - Fix: kontext nyní pracuje i se soubory typu `tree_Y.laz` (dříve se
    hledalo pouze `cloud_segmented_*`), soubor se hledá podle tree_id
    zaznamenaného v interní DB.
  - Background (-1) se hledá zároveň pod mask `*-1.laz`, tedy nejen
    `cloud_segmented_-1.laz` ale i `tree_-1.laz`.
  - Fix: při znovuotevření projektu (existující `*.db` s tabulkami
    files/categories/labels) aplikace otevře JI — ne vytváří novou.
    Pokud se celý folder přesunul, pokračuj v labelingu dál.
  - Funguje i bez sqlite (pokud tabulku trees neexistuje, použije se
    vlastní `<slozka>.db` vytvořená treelabelerem).

KONTROLA
  - 26 automatických testů prochází.
