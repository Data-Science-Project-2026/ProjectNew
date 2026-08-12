from database import engine
from sqlalchemy import text

try:
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print("Database connected:", result.fetchone())

except Exception as e:
    print("Database error:")
    print(e)