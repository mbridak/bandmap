"""
K6GTE, Database class to store contacts
Email: michael.bridak@gmail.com
GPL V3
"""

import sqlite3

if __name__ == "__main__":
    print("I'm not the program you are looking for.")


class DataBase:
    """Database class for our database."""

    def __init__(self, database):
        """initializes DataBase instance"""
        self.database = database

    @staticmethod
    def row_factory(cursor, row):
        """
        cursor.description:
        (name, type_code, display_size,
        internal_size, precision, scale, null_ok)
        row: (value, value, ...)
        """
        return {
            col[0]: row[idx]
            for idx, col in enumerate(
                cursor.description,
            )
        }

    def get_contacts(self) -> list:
        """returns a list of dicts with bands"""
        with sqlite3.connect(self.database) as conn:
            conn.row_factory = self.row_factory
            cursor = conn.cursor()
            cursor.execute("select * from contacts where mode='CW'")
            return cursor.fetchall()

    @staticmethod
    def getspots():
        """Return list of spots"""
        with sqlite3.connect("spots.db") as db_context:
            db_cursor = db_context.cursor()
            sql = (
                "select *, Cast ("
                "(JulianDay(datetime('now')) - JulianDay(date_time)) * 24 * 60 * 60 As Integer"
                ") from spots order by frequency asc"
            )
            db_cursor.execute(sql)
            return db_cursor.fetchall()

    @staticmethod
    def setup_spots_db(spot_to_old):
        """Setup spots db"""
        with sqlite3.connect("spots.db") as db_context:
            db_cursor = db_context.cursor()
            sql_table = (
                "CREATE TABLE IF NOT EXISTS spots (id INTEGER PRIMARY KEY, callsign text, "
                "date_time text NOT NULL, frequency REAL NOT NULL, band INTEGER);"
            )
            db_cursor.execute(sql_table)
            sql = (
                "delete from spots where Cast "
                "((JulianDay(datetime('now')) - JulianDay(date_time)) * 24 * 60 * 60 As Integer) "
                f"> {spot_to_old}"
            )
            db_cursor.execute(sql)
            db_context.commit()

    @staticmethod
    def prune_oldest_spot():
        """
        Removes the oldest spot.
        """
        with sqlite3.connect("spots.db") as db_context:
            db_cursor = db_context.cursor()
            sql = "select * from spots order by date_time asc"
            db_cursor.execute(sql)
            result = db_cursor.fetchone()
            spot_index, _, _, _, _ = result
            sql = f"delete from spots where id='{spot_index}'"
            db_cursor.execute(sql)
            db_context.commit()

    @staticmethod
    def add_spot(callsign, freq, band, spot_to_old):
        """
        Removes spots older than value stored in spottoold.
        Inserts a new or updates existing spot.
        """
        with sqlite3.connect("spots.db") as db_context:
            spot = (callsign, freq, band)
            db_cursor = db_context.cursor()
            sql = (
                "delete from spots where Cast ("
                "(JulianDay(datetime('now')) - JulianDay(date_time)"
                f") * 24 * 60 * 60 As Integer) > {spot_to_old}"
            )
            db_cursor.execute(sql)
            db_context.commit()
            sql = f"select count(*) from spots where callsign='{callsign}'"
            db_cursor.execute(sql)
            result = db_cursor.fetchall()
            if result[0][0] == 0:
                sql = (
                    "INSERT INTO spots(callsign, date_time, frequency, band) "
                    "VALUES(?,datetime('now'),?,?)"
                )
                db_cursor.execute(sql, spot)
                db_context.commit()
            else:
                sql = (
                    "update spots "
                    f"set frequency='{freq}', date_time = datetime('now'), band='{band}' "
                    f"where callsign='{callsign}';"
                )
                db_cursor.execute(sql)
                db_context.commit()
