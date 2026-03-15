from typing import List,Tuple

class PDFContent:
    def __init__(self):
        self.text: str = ""
        self.images_captions: List[Tuple[str, str]]   = []
    def add_text(self, text: str):
        """Add text content to the PDFContent."""
        self.text += text + "\n"    
    def add_image_caption(self, image_path: str, caption: str):
        """Add an image and its caption to the PDFContent."""
        self.images_captions.append((image_path, caption))
    def __str__(self):
        """Describe the PDFContent."""
        return f"PDFContent(text_length={len(self.text)}, images_count={len(self.images_captions)})"
        