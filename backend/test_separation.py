from services.separation import SeparationService
from pathlib import Path
import logging
import asyncio

logging.basicConfig(level=logging.INFO)

async def test_service_init():
    print("Testing SeparationService...")
    output_dir = Path("backend/processed")
    service = SeparationService(output_dir)
    print("Service initialized.")
    
    # We won't run full separation here as it needs a file and downloads big models
    # checking imports inside the method
    try:
        from audio_separator.separator import Separator
        print("Success: audio-separator library verified found.")
    except ImportError:
        print("FAILED: audio-separator not found.")

if __name__ == "__main__":
    asyncio.run(test_service_init())
