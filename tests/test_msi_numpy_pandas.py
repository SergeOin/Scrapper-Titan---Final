import re
from pathlib import Path

SCRIPT_PATH = Path('scripts/build_msi_folder.ps1')


def test_msi_script_contains_numpy_pandas_install_block():
    """Test léger: vérifie que le script MSI contient la logique d'installation auto numpy/pandas.

    On ne lance pas le script (environnement CI non Windows possiblement), mais on s'assure que:
      - Le script cherche 'pandas' et 'numpy' dans le dossier source
      - Il appelle pip install avec --target pour numpy ET pandas
    Cela sert de garde-fou pour éviter une régression supprimant le block.
    """
    content = SCRIPT_PATH.read_text(encoding='utf-8')
    # Indices de présence
    assert 'needsPandas' in content
    assert 'needsNumpy' in content
    # Vérifie la commande pip target (numpy + pandas)
    numpy_pattern = re.compile(r'pip install[^\n]+--target[^\n]+numpy', re.IGNORECASE)
    pandas_pattern = re.compile(r'pip install[^\n]+--target[^\n]+pandas', re.IGNORECASE)
    assert numpy_pattern.search(content), 'Bloc installation numpy manquant ou modifié'
    assert pandas_pattern.search(content), 'Bloc installation pandas manquant ou modifié'
