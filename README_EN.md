# PDF to Video App

This project is an application that converts PDF files into explanatory videos. Users can input a PDF file, and the application will extract text and images from it to generate an engaging explanatory video.

---

## Project Structure

```
pdf-to-video-app
├── src
│   ├── main.py              # Application entry point
│   ├── pdf_processor.py     # PDF processing module
│   ├── video_creator.py     # Video creation module
│   ├── utils
│   │   └── helpers.py       # Helper functions
│   └── types
│       └── index.py         # Type and interface definitions
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```

---

## Features

1. **PDF Processing**: Extract text and images from PDF files.
2. **Video Creation**: Combine extracted content into a video.
3. **Summary and Title Generation**: Generate engaging summaries and titles to attract viewers.

---

## Usage Instructions

### 1. Install Dependencies

Ensure all dependencies are installed. You can set up the environment using the following commands:

```bash
conda create -n paperagent python=3.10
conda activate paperagent
pip install -r requirements.txt
conda install -c conda-forge tesserocr
```

Additionally, modify the following lines in `anaconda3\envs\paperagent\lib\site-packages\deepdoctection\extern\tessocr.py`:

```python
# Add this before line 263
if not results:
    return all_results
```

```python
# Modify line 181 to remove the file extension
with open(tmp_name, "rb") as output_file:
```

### 2. Run the Application

Run the following command to start the application:

```bash
python src/main.py <path_to_pdf>
```

Replace `<path_to_pdf>` with the path to your PDF file.

---

## Contribution

We welcome contributions of any kind! Please submit issues or pull requests.

---

## License

This project is licensed under the MIT License.