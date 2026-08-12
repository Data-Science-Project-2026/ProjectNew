from sqlalchemy import create_engine
import pandas as pd


# PostgreSQL

pg_engine = create_engine(
    "postgresql://postgres:postgres123@localhost:5432/nature_dashboard"
)


# SQLite

sqlite_engine = create_engine(
    "sqlite:///dashboard.db"
)



tables = [

    "activity_trend_stats",

    "response_trend_stats",

    "monthly_genus_stats",

    "activity_map_stats",

    "species_map_stats",

    "human_response_map_stats",

    "cooccur_edges",

    "top15_activity",

    "top15_emotion",

    "species_filter_options"


]


for table in tables:


    print(
        "Migrating",
        table
    )


    df = pd.read_sql(
        f"SELECT * FROM {table}",
        pg_engine
    )


    df.to_sql(

        table,

        sqlite_engine,

        if_exists="replace",

        index=False

    )


print("Done")