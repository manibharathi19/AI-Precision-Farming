import sqlite3

def update_database_schema():
    """
    Add the 'location' column to the reports table if it doesn't exist.
    """
    conn = sqlite3.connect('farm_advisor.db')
    cursor = conn.cursor()
    
    # Check if the location column exists
    cursor.execute("PRAGMA table_info(reports)")
    columns = [column[1] for column in cursor.fetchall()]
    
    # Add the location column if it doesn't exist
    if 'location' not in columns:
        print("Adding 'location' column to reports table...")
        cursor.execute("ALTER TABLE reports ADD COLUMN location TEXT")
        conn.commit()
        print("Column added successfully!")
    else:
        print("'location' column already exists in reports table.")
    
    conn.close()

if __name__ == "__main__":
    update_database_schema()