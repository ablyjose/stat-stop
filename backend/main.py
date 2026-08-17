from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import fastf1
import os

from routers import data

# Setup Cache - Use /tmp on Vercel (read-only filesystem except /tmp)
if os.environ.get('VERCEL'):
    cache_dir = '/tmp/f1_cache'
else:
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')

if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
fastf1.Cache.enable_cache(cache_dir)

# Initialize R2 Cache Client
from r2_client import get_r2_client, R2_BUCKET_NAME
r2_client = get_r2_client()
if r2_client:
    print(f"Cloudflare R2 caching initialized successfully. Bucket: {R2_BUCKET_NAME}")
else:
    print("Warning: Cloudflare R2 caching is disabled. Credentials not configured in environment.")

app = FastAPI()

origins = [
    "http://localhost:5173",  # Vite default
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for Vercel deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)

@app.get("/")
def read_root():
    return {"message": "F1 Analysis API is running"}

