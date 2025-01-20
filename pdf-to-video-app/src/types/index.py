from typing import List

class PDFContent:
    def __init__(self, text: str, images: List[str]):
        self.text = text
        self.images = images