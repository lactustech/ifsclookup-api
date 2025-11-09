import os
import uvicorn
import re
import unicodedata
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

# --- App Setup ---
app = FastAPI(
    title="IFSC Lookup API & Frontend",
    description="Serves bank details and HTML pages for ifsclookup.in",
    version="2.0.0"
)

# --- Database Connection Pool ---
db_pool = None

def get_db_pool():
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
    return db_pool

# --- Dependency Injection for DB Connection ---
def get_db_conn():
    pool = get_db_pool()
    if pool is None:
        raise HTTPException(status_code=503, detail="Database connection pool is not available")
    try:
        conn = pool.getconn()
        yield conn
    finally:
        if conn:
            pool.putconn(conn)

# --- Jinja2 Template Setup ---
templates = Jinja2Templates(directory="templates")

# --- Helper Function ---
def slugify(value):
    value = str(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '-', value)
    return value

# --- HTML Page Endpoints (Your Website) ---

@app.get("/", response_class=HTMLResponse)
async def get_homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/banks", response_class=HTMLResponse)
async def get_banks_list(request: Request, conn=Depends(get_db_conn)):
    bank_list = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT DISTINCT bank FROM branches ORDER BY bank ASC")
            rows = cur.fetchall()
            
            for row in rows:
                bank_list.append({
                    "bank_name": row['bank'],
                    "bank_slug": slugify(row['bank'])
                })
        
        return templates.TemplateResponse("banks_list.html", {
            "request": request,
            "banks": bank_list
        })
            
    except Exception as e:
        print(f"Error getting bank list: {e}")
        return templates.TemplateResponse("index.html", {
            "request": request, 
            "error": "Could not load bank list."
        })

# --- === NEW ENDPOINT (THE FIX) === ---
# This new endpoint catches the /bank/... URLs
@app.get("/bank/{bank_slug}", response_class=HTMLResponse)
async def get_states_list(request: Request, bank_slug: str, conn=Depends(get_db_conn)):
    """
    Serves the page listing all states for a specific bank.
    """
    state_list = []
    real_bank_name = ""
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # This is tricky: we have to find the *real bank name* from the slug
            # This is a bit slow, but necessary with our data structure.
            cur.execute("SELECT DISTINCT bank FROM branches")
            all_banks = cur.fetchall()
            
            for row in all_banks:
                if slugify(row['bank']) == bank_slug:
                    real_bank_name = row['bank']
                    break
            
            if not real_bank_name:
                # If no bank matches the slug, return a 404
                raise HTTPException(status_code=404, detail="Bank not found")

            # Now, find all states for that bank
            cur.execute(
                "SELECT DISTINCT state FROM branches WHERE bank = %s ORDER BY state ASC", 
                (real_bank_name,)
            )
            states = cur.fetchall()
            
            for row in states:
                state_list.append({
                    "state_name": row['state'],
                    "state_slug": slugify(row['state'])
                })
        
        return templates.TemplateResponse("states_list.html", {
            "request": request,
            "bank_name": real_bank_name,
            "bank_slug": bank_slug,
            "states": state_list
        })
            
    except Exception as e:
        print(f"Error getting states list: {e}")
        # Send user back to the banks list on error
        return templates.TemplateResponse("banks_list.html", {
            "request": request, 
            "error": f"Could not load states for {bank_slug}."
        })


@app.get("/ifsc/{code}", response_class=HTMLResponse)
async def get_ifsc_page(request: Request, code: str, conn=Depends(get_db_conn)):
    search_code = code.upper()
    branch_data = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql_query = """
                SELECT * FROM branches 
                WHERE REGEXP_REPLACE(UPPER(ifsc), '[^A-Z0-9]', '', 'g') = %s
            """
            cur.execute(sql_query, (search_code,))
            branch_data = cur.fetchone()
        
        return templates.TemplateResponse("results.html", {
            "request": request,
            "data": branch_data,
            "code": search_code
        })
            
    except Exception as e:
        print(f"Error getting IFSC page: {e}")
        return templates.TemplateResponse("results.html", {
            "request": request, 
            "data": None, 
            "code": search_code, 
            "error": "A database error occurred."
        })

# --- JSON API Endpoint ---
@app.get("/api/ifsc/{code}")
async def get_ifsc_api(code: str, conn=Depends(get_db_conn)):
    search_code = code.upper()
    branch_data = None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql_query = """
                SELECT * FROM branches 
                WHERE REGEXP_REPLACE(UPPER(ifsc), '[^A-Z0-9]', '', 'g') = %s
            """
            cur.execute(sql_query, (search_code,))
            branch_data = cur.fetchone()
        
        if branch_data:
            return branch_data
        else:
            raise HTTPException(status_code=404, detail="IFSC code not found")
            
    except Exception as e:
        print(f"Error in API query: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- Uvicorn Server (for Render) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)