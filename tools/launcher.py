"""Entry point pro PyInstaller bundled treelabeler - obali import a spusti main."""

import sys
from pathlib import Path

# Pridame "src" do sys.path, aby "treelabeler" byl najiteny jako balicek
bundle_dir = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else Path(__file__).parent
sys.path.insert(0, str(bundle_dir))

from treelabeler.__main__ import main

if __name__ == '__main__':
    sys.exit(main())
