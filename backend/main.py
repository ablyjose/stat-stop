from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import fastf1
import os

from routers import data

# Setup Cache
cache_dir = os.path.join(os.getcwd(), '..', '..', 'cache')
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
fastf1.Cache.enable_cache(cache_dir)

app = FastAPI()

origins = [
    "http://localhost:5173",  # Vite default
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router)

@app.get("/")
def read_root():
    return {"message": "F1 Analysis API is running"}
