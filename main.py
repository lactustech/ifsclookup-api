import os
import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

# --- App Setup ---
app = FastAPI(
    title="IFSC Lookup API",
    description="A simple API to find bank details from an IFSC code.",
    version="1.0.0"
)

# --- CORS (Cross-Origin Resource Sharing) ---
# THIS IS THE FIX: We are allowing all domains to make
# requests. This is the simplest and most robust fix.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# --- Database Connection Pool ---
db_pool = None

async def get_db_conn():
    """
    Gets a connection from the pool.
    """
    global db_pool
    if db_pool is None:
        try:
            # Get the connection string from the environment variable
            conn_string = os.environ.get("NEON_CONNECTION_STRING")
            if not conn_string:
                raise Exception("NEON_CONNECTION_STRING environment variable not set.")
                
            db_pool = SimpleConnectionPool(1, 5, dsn=conn_string)
            print("Database connection pool created.")
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            return None
            
    try:
        conn = db_pool.getconn()
        return conn
    except Exception as e:
        print(f"Error getting connection from pool: {e}")
        return None

def put_db_conn(conn):
    """
    Returns a connection to the pool.
    """
    if db_pool:
        db_pool.putconn(conn)

async def close_db_pool():
    """
    Closes all connections in the pool on shutdown.
    """
    if db_pool:
        db_pool.closeall()
        print("Database connection pool closed.")

app.add_event_handler("shutdown", close_db_pool)

# --- API Endpoints ---
@app.get("/")
def read_root():
    return {"status": "ok", "message": "IFSC Lookup API is running"}

@app.get("/ifsc/{query_ifsc}")
async def get_ifsc_details(query_ifsc: str):
    # --- THE FIX (V4) ---
    # We will uppercase the user's input to match our clean database.
    search_code = query_ifsc.upper()

    conn = await get_db_conn()
    if conn is None:
        raise HTTPException(status_code=503, detail="Database connection error")
        
    branch = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # RealDictCursor returns results as dictionaries (like JSON)
            
            # --- THE FIX (V4) ---
            # Since our load script now cleans the data, we can use
            # a simple, fast, and indexed query.
            cur.execute("SELECT * FROM branches WHERE ifsc = %s", (search_code,))
            branch = cur.fetchone()
        
        if branch:
            return branch
        else:
            raise HTTPException(status_code=404, detail="IFSC code not found")
            
    except Exception as e:
        print(f"Error during query: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    finally:
        if conn:
            put_db_conn(conn)
