import os
import mysql.connector

def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASS", "blank"),
        database=os.getenv("DB_NAME", "cigarra_db"),
        port=int(os.getenv("DB_PORT", 3306))
    )