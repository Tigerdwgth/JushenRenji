import os
import sys
import logging
from PIL import Image

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

import logging
import sys

# Configure logging to print to stderr
logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

from src.llm_tools.image_agent import ImageAgent

# Unset proxy for testing DashScope connection
if "http_proxy" in os.environ:
    del os.environ["http_proxy"]
if "https_proxy" in os.environ:
    del os.environ["https_proxy"]
if "HTTP_PROXY" in os.environ:
    del os.environ["HTTP_PROXY"]
if "HTTPS_PROXY" in os.environ:
    del os.environ["HTTPS_PROXY"]

from src.config import DASHSCOPE_API_KEY

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def test_explain_image():
    print(f"DASHSCOPE_API_KEY present: {bool(DASHSCOPE_API_KEY)}")
    if DASHSCOPE_API_KEY:
        print(f"DASHSCOPE_API_KEY prefix: {DASHSCOPE_API_KEY[:4]}...")
    
    image_path = "/home/jdh/Projects/VlogCutter/JushenRenji/output/daily_summary.png"
    if not os.path.exists(image_path):
        print(f"Image not found at {image_path}, creating a dummy image.")
        img = Image.new('RGB', (100, 100), color = 'red')
        img.save(image_path)
    else:
        print(f"Using image at {image_path}")

    agent = ImageAgent(ocr_fallback=False)
    print(f"Agent model: {agent.model}")
    
    try:
        # Test with file path string
        print("\n--- Testing with file path string ---")
        result = agent.explain_image(image_path, caption_text="Test Chart")
        print("Result:", result)
        
        # Test with PIL Image
        print("\n--- Testing with PIL Image ---")
        img = Image.open(image_path)
        result_pil = agent.explain_image(img, caption_text="Test Chart PIL")
        print("Result PIL:", result_pil)

    except Exception as e:
        print(f"Error during test: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_explain_image()
