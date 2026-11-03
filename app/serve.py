"""Portable local/Render entry point; one worker owns process-local sessions."""
import os

import uvicorn
from dotenv import load_dotenv

from app.config import PROJECT_ROOT


if __name__ == "__main__":
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    uvicorn.run("app.main:app", host=os.getenv("HOST", "0.0.0.0"),
                port=int(os.getenv("PORT", "8000")), workers=1)
