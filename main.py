import os
import uvicorn
from fastapi import FastAPI, HTTPException, Request
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
    version="2.0.0"
)

# --- Add HTML Templating ---
# This tells FastAPI to look for HTML files in a folder named "templates"
templates = Jinja2Templates(directory="templates")

# --- CORS (Cross-Origin Resource Sharing) ---
# This is still needed for any future tools you build.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Database Connection Pool (No changes) ---
db_pool = None

async def get_db_conn():
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
            return None
    try:
        conn = db_pool.getconn()
        return conn
    except Exception as e:
        print(f"Error getting connection from pool: {e}")
        return None

def put_db_conn(conn):
    if db_pool:
        db_pool.putconn(conn)

async def close_db_pool():
    if db_pool:
        db_pool.closeall()
        print("Database connection pool closed.")

app.add_event_handler("shutdown", close_db_pool)

# --- Helper Function ---
async def fetch_ifsc_data(query_ifsc: str):
    """Helper function to get data from the DB."""
    search_code = query_ifsc.upper()
    
    conn = await get_db_conn()
    if conn is None:
        return None
        
    branch = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # We use the clean, fast query
            cur.execute("SELECT * FROM branches WHERE ifsc = %s", (search_code,))
            branch = cur.fetchone()
        return branch
    except Exception as e:
        print(f"Error during query: {e}")
        return None
    finally:
        if conn:
            put_db_conn(conn)

# --- 1. THE WEBSITE PAGES (pSEO) ---

@app.get("/", response_class=HTMLResponse)
async def get_homepage(request: Request):
    """
    Serves the homepage (index.html) with the search bar.
    """
    # The "request" object is required by Jinja2
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/ifsc/{code}", response_class=HTMLResponse)
async def get_ifsc_page(request: Request, code: str):
    """
    This is the PSEO PAGE, just like your competitor!
    It gets a code, fetches the data, and renders the results.html page.
    """
    data = await fetch_ifsc_data(code)
    
    # We pass the data to the results.html template
    return templates.TemplateResponse("results.html", {
        "request": request,
        "code": code,
        "data": data  # This will be None if not found, and the template will handle it
    })

# --- 2. THE JSON API (for other people to use) ---
# We'll put this on a separate path like "/api/"

@app.get("/api/status")
def read_root():
    return {"status": "ok", "message": "IFSC Lookup API is running"}

@app.get("/api/ifsc/{query_ifsc}")
async def get_ifsc_api(query_ifsc: str):
    """
    This is the JSON API endpoint.
    """
    branch = await fetch_ifsc_data(query_ifsc)
    
    if branch:
        return branch
    else:
        raise HTTPException(status_code=404, detail="IFSC code not found")
