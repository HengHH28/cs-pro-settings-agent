from langchain.tools import tool
import sqlite3
import os


DB_PATH = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
    "database",
    "players.db",
)


@tool
def query_players_database(sql_query: str):
    """
    Execute SQL query on CS2 professional player database.

    Use this tool when user asks for:
    - list of players
    - filtering players
    - statistics query
    - team query
    - equipment query

    Input:
    Valid SQLite SELECT statement.

    Return:
    Query results.
    """

    # 安全限制，只允许查询

    if not sql_query.lower().strip().startswith("select"):
        return "Only SELECT queries are allowed."

    # 数据库文件不存在时直接返回，避免 sqlite3.connect 静默创建空库
    if not os.path.exists(DB_PATH):
        return "Database not found"
    
    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True,
    )
    conn.execute("PRAGMA query_only = ON")
    cursor = conn.cursor()


    try:

        cursor.execute(sql_query)

        rows = cursor.fetchall()


        if not rows:
            return "No results found."


        columns = [
            description[0]
            for description in cursor.description
        ]


        result = []

        for row in rows:
            result.append(
                dict(zip(columns,row))
            )


        return result


    except Exception as e:

        return f"SQL Error: {str(e)}"


    finally:

        conn.close()
