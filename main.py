import os
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# --- Database Connection ---

# Get the database connection string from an environment variable
# This is a security best practice. We'll set this in our hosting platform.
DATABASE_URL = os.environ.get("NEON_CONNECTION_STRING")

def get_db_connection():
    """Establishes a connection to the database."""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"Error connecting to database: {e}")
        return None

# --- API Models (Data Shape) ---

# This defines what our API response will look like
class BranchDetails(BaseModel):
    bank: Optional[str]
    ifsc: str
    branch: Optional[str]
    centre: Optional[str]
    district: Optional[str]
    state: Optional[str]
    address: Optional[str]
    contact: Optional[str]
    imps: Optional[bool]
    rtgs: Optional[bool]
    city: Optional[str]
    iso3166: Optional[str]
    neft: Optional[bool]
    micr: Optional[str]
    upi: Optional[bool]
    swift: Optional[str]

# --- FastAPI App ---

app = FastAPI()

# --- CORS Middleware ---
# This is CRITICAL. It allows your frontend website (on ifsclookup.in)
# to make requests to this API (which will be on a different domain).
origins = [
    "http://localhost",
    "http://localhost:3000",
    "https://ifsclookup.in",  # Your production domain
    "https://www.ifsclookup.in", # www version
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For simplicity, we'll allow all. Can restrict to `origins` later.
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],
)

# --- API Endpoints ---

@app.get("/")
def read_root():
    """A simple root endpoint to check if the API is running."""
    return {"status": "ok", "message": "IFSC Lookup API is running"}


@app.get("/ifsc/{ifsc_code}", response_model=BranchDetails, status_code=status.HTTP_200_OK)
def get_ifsc_details(ifsc_code: str):
    """
    Takes an IFSC code, queries the database, and returns the branch details.
    """
    
    # Sanitize and format the input
    query_ifsc = ifsc_code.strip().upper()
    
    conn = get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Database connection error")

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            # RealDictCursor returns results as dictionaries (like JSON)
            cur.execute("SELECT * FROM branches WHERE TRIM(ifsc) = %s", (query_ifsc,))
            branch = cur.fetchone()
        
        if branch:
            return branch
        else:
            # If no branch is found, return a 404 error
            raise HTTPException(status_code=404, detail="IFSC code not found")
            
    except Exception as e:
        print(f"Error during query: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
        
    finally:
        if conn:

            conn.close()

