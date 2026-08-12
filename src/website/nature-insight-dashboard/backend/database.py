from pathlib import Path
import sys
from sqlalchemy import create_engine


if getattr(sys,"frozen",False):

    BASE_DIR = Path(sys.executable).parent

else:

    BASE_DIR = Path(__file__).parent


DB_PATH = BASE_DIR / "dashboard.db"

print("Database path:", DB_PATH)
print("Exists:", DB_PATH.exists())


DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL
)