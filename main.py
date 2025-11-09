import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
import re

# --- App Setup ---
app = FastAPI(
    title="IFSC Lookup API & Web",
    description="Serves both the API and the pSEO-friendly website.",
    version="2.1.0" # Version bump
)

# --- Add HTML Templating ---
templates = Jinja2Templates(directory="templates")

# --- CORS (Cross-Origin Resource Sharing) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Connection Pool ---
db_pool = None

# This is the NEW, SAFER way to get a DB connection
def get_db_conn():
    """
    This function is a FastAPI "dependency".
    It will be called for every request that needs a database connection.
    It uses 'yield' to give the connection to the endpoint,
    and the 'finally' block *guarantees* the connection is returned.
    """
    global db_pool
    if db_pool is None:
        try:
            conn_string = os.environ.get("NEON_CONNECTION_STRING")
            if not conn_string:
                raise Exception("NEON_CONNECTION_STRING environment variable not set.")
            db_pool = SimpleConnectionPool(1, 5, dsn=conn_string)
            print("Database connection pool created.")
        except Exception as e:
            print(f"Error creating connection pool: {e}")
            raise HTTPException(status_code=503, detail="Database connection error")
            
    conn = None
    try:
        conn = db_pool.getconn()
        yield conn  # Provide the connection to the endpoint
    except Exception as e:
        print(f"Error getting connection from pool: {e}")
        raise HTTPException(status_code=503, detail="Database connection error")
    finally:
        if conn:
            db_pool.putconn(conn) # This will ALWAYS run, fixing the bug

# We no longer need the 'close_db_pool' handler,
# Render will handle shutting down the app.

# --- Helper Function ---
# Note: It now takes 'conn' as an argument!
async def fetch_ifsc_data(query_ifsc: str, conn):
    """Helper function to get data from the DB."""
    search_code = query_ifsc.upper()
    
    if conn is None:
        return None
        
    branch = None
    try:
        # We use 'with' to auto-close the cursor
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT * FROM branches WHERE ifsc = %s", (search_code,))
            branch = cur.fetchone()
        return branch
    except Exception as e:
        print(f"Error during query: {e}")
        return None
    # We no longer need a 'finally' block here, the dependency handles it.

# --- 1. THE WEBSITE PAGES (pSEO) ---

@app.get("/", response_class=HTMLResponse)
async def get_homepage(request: Request):
    """
    Serves the homepage (index.html) with the search bar.
    This endpoint does not need a database connection.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/ifsc/{code}", response_class=HTMLResponse)
async def get_ifsc_page(request: Request, code: str, conn = Depends(get_db_conn)):
    """
    This is the PSEO PAGE.
    FastAPI will automatically provide the 'conn' variable by calling get_db_conn.
    """
    data = await fetch_ifsc_data(code, conn)
    
    return templates.TemplateResponse("results.html", {
        "request": request,
        "code": code,
        "data": data 
    })

# --- 2. THE JSON API (for other people to use) ---

@app.get("/api/status")
def read_root():
    return {"status": "ok", "message": "IFSC Lookup API is running"}

@app.get("/api/ifsc/{query_ifsc}")
async def get_ifsc_api(query_ifsc: str, conn = Depends(get_db_conn)):
    """
    This is the JSON API endpoint.
    It also gets the 'conn' variable from the dependency.
    """
    branch = await fetch_ifsc_data(query_ifsc, conn)
    
    if branch:
        return branch
    else:
        raise HTTPException(status_code=404, detail="IFSC code not found")