"""Keystone entrypoint. Delegates directly to backend.app."""
import os
import uvicorn
from backend.app import app

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=False)
