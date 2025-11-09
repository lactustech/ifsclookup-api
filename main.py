import os
import uvicorn
import re
import unicodedata
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response, StreamingResponse
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
import io
import math

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
    conn = None # Initialize conn
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
    if not value:
        return ""
    value = str(value)
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value).strip().lower()
    value = re.sub(r'[-\s]+', '-', value)
    return value

# --- Helper to find real names from slugs ---
def get_real_names(conn, bank_slug=None, state_slug=None, city_slug=None):
    real_bank_name = None
    real_state_name = None
    real_city_name = None
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if bank_slug:
            cur.execute("SELECT DISTINCT bank FROM branches")
            for row in cur.fetchall():
                if slugify(row['bank']) == bank_slug:
                    real_bank_name = row['bank']
                    break
            if not real_bank_name: raise HTTPException(status_code=404, detail="Bank not found")
        
        if state_slug and real_bank_name:
            cur.execute("SELECT DISTINCT state FROM branches WHERE bank = %s", (real_bank_name,))
            for row in cur.fetchall():
                if slugify(row['state']) == state_slug:
                    real_state_name = row['state']
                    break
            if not real_state_name: raise HTTPException(status_code=404, detail="State not found for this bank")

        if city_slug and real_bank_name and real_state_name:
            cur.execute("SELECT DISTINCT city FROM branches WHERE bank = %s AND state = %s", (real_bank_name, real_state_name))
            for row in cur.fetchall():
                if slugify(row['city']) == city_slug:
                    real_city_name = row['city']
                    break
            if not real_city_name: raise HTTPException(status_code=404, detail="City not found for this bank/state")
            
    return real_bank_name, real_state_name, real_city_name


# --- HTML Page Endpoints (Your Website) ---

@app.get("/", response_class=HTMLResponse)
async def get_homepage(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/banks", response_class=HTMLResponse)
async def get_banks_list(request: Request, conn=Depends(get_db_conn)):
    bank_list = []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT bank, COUNT(*) as branch_count FROM branches GROUP BY bank ORDER BY bank ASC")
            rows = cur.fetchall()
            
            for row in rows:
                bank_list.append({
                    "bank_name": row['bank'],
                    "bank_slug": slugify(row['bank']),
                    "branch_count": row['branch_count']
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

@app.get("/bank/{bank_slug}", response_class=HTMLResponse)
async def get_states_list(request: Request, bank_slug: str, conn=Depends(get_db_conn)):
    state_list = []
    try:
        real_bank_name, _, _ = get_real_names(conn, bank_slug=bank_slug)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT state, COUNT(*) as branch_count FROM branches WHERE bank = %s GROUP BY state ORDER BY state ASC", 
                (real_bank_name,)
            )
            states = cur.fetchall()
            
            for row in states:
                state_list.append({
                    "state_name": row['state'],
                    "state_slug": slugify(row['state']),
                    "branch_count": row['branch_count']
                })
        
        return templates.TemplateResponse("states_list.html", {
            "request": request,
            "bank_name": real_bank_name,
            "bank_slug": bank_slug,
            "states": state_list
        })
            
    except Exception as e:
        print(f"Error getting states list: {e}")
        raise HTTPException(status_code=404, detail=f"Error: {e}")


@app.get("/bank/{bank_slug}/{state_slug}", response_class=HTMLResponse)
async def get_cities_list(request: Request, bank_slug: str, state_slug: str, conn=Depends(get_db_conn)):
    city_list = []
    try:
        real_bank_name, real_state_name, _ = get_real_names(conn, bank_slug=bank_slug, state_slug=state_slug)

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT city, COUNT(*) as branch_count FROM branches WHERE bank = %s AND state = %s GROUP BY city ORDER BY city ASC", 
                (real_bank_name, real_state_name)
            )
            cities = cur.fetchall()
            
            for row in cities:
                city_list.append({
                    "city_name": row['city'],
                    "city_slug": slugify(row['city']),
                    "branch_count": row['branch_count']
                })
        
        return templates.TemplateResponse("cities_list.html", {
            "request": request,
            "bank_name": real_bank_name,
            "bank_slug": bank_slug,
            "state_name": real_state_name,
            "state_slug": state_slug,
            "cities": city_list
        })
            
    except Exception as e:
        print(f"Error getting cities list: {e}")
        raise HTTPException(status_code=404, detail=f"Error: {e}")


@app.get("/bank/{bank_slug}/{state_slug}/{city_slug}", response_class=HTMLResponse)
async def get_branches_list(request: Request, bank_slug: str, state_slug: str, city_slug: str, conn=Depends(get_db_conn)):
    branch_list = []
    try:
        real_bank_name, real_state_name, real_city_name = get_real_names(
            conn, bank_slug=bank_slug, state_slug=state_slug, city_slug=city_slug
        )

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT branch, ifsc, address FROM branches 
                WHERE bank = %s AND state = %s AND city = %s 
                ORDER BY branch ASC
                """, 
                (real_bank_name, real_state_name, real_city_name)
            )
            branches = cur.fetchall()
            
            for row in branches:
                branch_list.append({
                    "branch_name": row['branch'],
                    "ifsc_code": row['ifsc'],
                    "address": row['address']
                })
        
        return templates.TemplateResponse("branches_list.html", {
            "request": request,
            "bank_name": real_bank_name,
            "bank_slug": bank_slug,
            "state_name": real_state_name,
            "state_slug": state_slug,
            "city_name": real_city_name,
            "city_slug": city_slug,
            "branches": branch_list
        })
            
    except Exception as e:
        print(f"Error getting branches list: {e}")
        raise HTTPException(status_code=404, detail=f"Error: {e}")


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
        
        # We need slugs for the breadcrumbs
        bank_slug = ""
        state_slug = ""
        city_slug = ""
        if branch_data:
            bank_slug = slugify(branch_data.get('bank'))
            state_slug = slugify(branch_data.get('state'))
            city_slug = slugify(branch_data.get('city'))

        return templates.TemplateResponse("results.html", {
            "request": request,
            "branch": branch_data, # Pass 'branch' not 'data'
            "code": search_code,
            "bank_slug": bank_slug,
            "state_slug": state_slug,
            "city_slug": city_slug
        })
            
    except Exception as e:
        print(f"Error getting IFSC page: {e}")
        return templates.TemplateResponse("results.html", {
            "request": request, 
            "branch": None, 
            "code": search_code, 
            "error": "A database error occurred."
        })

# --- JSON API Endpoint (for future use / 3rd parties) ---
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

# --- robots.txt ---
@app.get("/robots.txt", response_class=Response)
async def get_robots_txt():
    content = """
User-agent: *
Allow: /
Sitemap: https://ifsclookup.in/sitemap.xml
""".strip()
    return Response(content=content, media_type="text/plain")


# --- NEW SITEMAP SECTION: Static Pages ---
@app.get("/sitemap-static.xml", response_class=Response)
async def get_sitemap_static():
    """
    This sitemap contains the static/main pages.
    """
    base_url = "https://ifsclookup.in"
    content = io.StringIO()
    content.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    content.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    
    # Add static pages
    content.write(f'  <url><loc>{base_url}/</loc><priority>1.0</priority></url>\n')
    content.write(f'  <url><loc>{base_url}/banks</loc><priority>0.8</priority></url>\n')
    
    content.write('</urlset>\n')
    return Response(content=content.getvalue(), media_type="application/xml")


# --- NEW SITEMAP SECTION: Bank List Pages ---
@app.get("/sitemap-banks.xml", response_class=Response)
async def get_sitemap_banks(conn=Depends(get_db_conn)):
    """
    This sitemap contains the /bank/{bank_slug} pages.
    """
    base_url = "https://ifsclookup.in"
    content = io.StringIO()
    content.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    content.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT DISTINCT bank FROM branches ORDER BY bank")
            for row in cur.fetchall():
                bank_slug = slugify(row['bank'])
                if bank_slug:
                    content.write(f'  <url><loc>{base_url}/bank/{bank_slug}</loc><priority>0.8</priority></url>\n')
    except Exception as e:
        print(f"Error generating sitemap-banks.xml: {e}")
    
    content.write('</urlset>\n')
    return Response(content=content.getvalue(), media_type="application/xml")


# --- NEW SITEMAP SECTION: State List Pages ---
@app.get("/sitemap-states.xml", response_class=Response)
async def get_sitemap_states(conn=Depends(get_db_conn)):
    """
    This sitemap contains the /bank/{bank_slug}/{state_slug} pages.
    """
    base_url = "https://ifsclookup.in"
    content = io.StringIO()
    content.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    content.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT DISTINCT bank, state FROM branches ORDER BY bank, state")
            for row in cur.fetchall():
                bank_slug = slugify(row['bank'])
                state_slug = slugify(row['state'])
                if bank_slug and state_slug:
                    content.write(f'  <url><loc>{base_url}/bank/{bank_slug}/{state_slug}</loc><priority>0.7</priority></url>\n')
    except Exception as e:
        print(f"Error generating sitemap-states.xml: {e}")
    
    content.write('</urlset>\n')
    return Response(content=content.getvalue(), media_type="application/xml")


# --- NEW SITEMAP SECTION: City List Pages (Paginated) ---
async def sitemap_cities_generator(conn, page: int):
    """
    Streams a single sitemap page for city-level pages.
    """
    base_url = "https://ifsclookup.in"
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    
    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    try:
        # Use a named cursor for streaming
        with conn.cursor(name=f'sitemap_city_page_{page}', cursor_factory=RealDictCursor) as cur:
            cur.itersize = 1000 # Fetch 1000 at a time
            
            sql_query = """
                SELECT DISTINCT bank, state, city FROM branches 
                ORDER BY bank, state, city 
                LIMIT %s OFFSET %s
            """
            cur.execute(sql_query, (SITEMAP_PAGE_SIZE, offset))
            
            for row in cur:
                bank_slug = slugify(row['bank'])
                state_slug = slugify(row['state'])
                city_slug = slugify(row['city'])
                if bank_slug and state_slug and city_slug:
                    yield f'  <url><loc>{base_url}/bank/{bank_slug}/{state_slug}/{city_slug}</loc><priority>0.7</priority></url>\n'
                    
    except Exception as e:
        print(f"Error generating sitemap city page {page}: {e}")
    finally:
        yield '</urlset>\n'

@app.get("/sitemap-cities-{page}.xml", response_class=Response)
async def get_sitemap_cities_page(page: int, conn=Depends(get_db_conn)):
    """
    Serves a specific page of the cities sitemap.
    """
    return StreamingResponse(sitemap_cities_generator(conn, page), media_type="application/xml")


# --- SITEMAP SECTION: Branch Pages (Paginated) ---
# (This section was already in your code and is correct)
SITEMAP_PAGE_SIZE = 20000

async def sitemap_branches_generator(conn, page: int):
    """
    Streams a single sitemap page for 20,000 branches.
    """
    base_url = "https://ifsclookup.in"
    offset = (page - 1) * SITEMAP_PAGE_SIZE
    
    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    
    try:
        # Use a named cursor for streaming
        with conn.cursor(name=f'sitemap_branch_page_{page}', cursor_factory=RealDictCursor) as cur:
            cur.itersize = 1000 # Fetch 1000 at a time from the 20k
            
            sql_query = """
                SELECT ifsc FROM branches 
                ORDER BY ifsc 
                LIMIT %s OFFSET %s
            """
            cur.execute(sql_query, (SITEMAP_PAGE_SIZE, offset))
            
            for row in cur:
                ifsc = "".join(c for c in row['ifsc'] if c.isalnum()).upper()
                if ifsc:
                    yield f'  <url><loc>{base_url}/ifsc/{ifsc}</loc><priority>0.6</priority></url>\n'
                    
    except Exception as e:
        print(f"Error generating sitemap branch page {page}: {e}")
    finally:
        yield '</urlset>\n'

@app.get("/sitemap-branches-{page}.xml", response_class=Response)
async def get_sitemap_branches_page(page: int, conn=Depends(get_db_conn)):
    """
    Serves a specific page of the branches sitemap.
    """
    return StreamingResponse(sitemap_branches_generator(conn, page), media_type="application/xml")


# --- MODIFIED SITEMAP INDEX ---
@app.get("/sitemap.xml", response_class=Response)
async def get_sitemap_index(request: Request, conn=Depends(get_db_conn)):
    """
    This is the sitemap index. It points to all the sub-sitemaps.
    """
    base_url = "httpss://ifsclookup.in" # <-- TYPO FIXED
    sitemap_content = io.StringIO()
    sitemap_content.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    sitemap_content.write('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
    
    try:
        # 1. Add static pages sitemap
        sitemap_content.write(f'  <sitemap><loc>{base_url}/sitemap-static.xml</loc></sitemap>\n')
        
        # 2. Add bank list sitemap
        sitemap_content.write(f'  <sitemap><loc>{base_url}/sitemap-banks.xml</loc></sitemap>\n')

        # 3. Add state list sitemap
        sitemap_content.write(f'  <sitemap><loc>{base_url}/sitemap-states.xml</loc></sitemap>\n')

        # 4. Add paginated city list sitemaps
        with conn.cursor() as cur:
            # Note: This count query might be slow. If it times out, 
            # you may need to optimize or cache the result.
            cur.execute("SELECT COUNT(DISTINCT (bank, state, city)) FROM branches")
            total_cities = cur.fetchone()[0]
            
        num_city_pages = math.ceil(total_cities / SITEMAP_PAGE_SIZE)
        for i in range(num_city_pages):
            page_num = i + 1
            sitemap_content.write(f'  <sitemap><loc>{base_url}/sitemap-cities-{page_num}.xml</loc></sitemap>\n')

        # 5. Add paginated branch (IFSC) sitemaps
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM branches")
            total_branches = cur.fetchone()[0]
            
        num_branch_pages = math.ceil(total_branches / SITEMAP_PAGE_SIZE)
        for i in range(num_branch_pages):
            page_num = i + 1
            sitemap_content.write(f'  <sitemap><loc>{base_url}/sitemap-branches-{page_num}.xml</loc></sitemap>\n')
        
    except Exception as e:
        print(f"Error generating sitemap index: {e}")
        # Even if it fails, close the tag
        pass
        
    sitemap_content.write('</sitemapindex>\n')
    return Response(content=sitemap_content.getvalue(), media_type="application/xml")


# --- Uvicorn Server (for Render) ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)