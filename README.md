# pdf-to-video-app/pdf-to-video-app/README.md

# PDF to Video App

该项目是一个将PDF文件转换为讲解视频的应用程序。用户可以输入一个PDF文件，应用程序将提取其中的文本和图片，并生成一个引人注目的讲解视频。

## 项目结构
目前代码还有一些杂乱
```
├── app.log
├── cache
│   └── cached_pdf.pdf
├── config.yaml
├── font
│   ├── eng.traineddata
│   └── SIMHEI.TTF
├── npm-debug.log
├── output
│   ├── cover.png
│   ├── daily_summary.mp4
│   ├── daily_summary.png
│   └── part_1.mp4
├── package.json
├── pic
│   ├── 1.png
│   ├── 2.png
│   ├── 3.png
│   ├── 4.png
│   ├── 5.png
│   ├── 6.png
│   └── 7.png
├── README_EN.md
├── README.md
├── requirements.txt
└── src
    ├── auto_upload_bilibili.py
    ├── code_interpreter.py
    ├── config.py
    ├── distribution
    ├── extract_images_from_pdf.py
    ├── generate_cover.py
    ├── get_arxiv_latest.py
    ├── get_website_data.py
    ├── gui.py
    ├── llm_agent.py
    ├── main.py
    ├── pdf_processor.py
    ├── __pycache__
    ├── types
    ├── utils
    └── video_creator.py
```

## 功能

1. **PDF处理**：从PDF文件中提取文本和图片。
2. **视频创建**：将提取的内容合成视频。
3. **摘要和标题生成**：生成引人注目的摘要和标题，以吸引观众。

## 使用说明

1. 确保已安装所有依赖项。可以通过以下命令安装：
   安装tesseract-ocr，参照
   <https://tesseract-ocr.github.io/tessdoc/Installation.html>

   ```
   conda create -n paperagent python=3.10
   conda activate paperagent
   pip install -r requirements.txt
   pip3 install torch torchvision torchaudio #linux
   pip3 install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126 #win


   pip install -e .
   ```


## 安装小红书MCP服务
   conda install conda-forge::nodejs
   # Run from your project's root directory
   npm init playwright@latest
   # Or create a new project
   npm init playwright@latest new-project
   

请修改
anaconda3\envs\paperagent\lib\site-packages\deepdoctection\extern\tessocr.py
```python
   # 263行 前加入
   if not results:
      return all_results
```
```python
   #181行 删掉文件后缀名
   with open(tmp_name , "rb") as output_file:
```

1. 运行应用程序：
   ```
   python src/main.py --filename "{papername}"
   ```

   <!-- 替换 `<path_to_pdf>` 为你的PDF文件路径。 -->


## 贡献

欢迎任何形式的贡献！请提交问题或拉取请求。

## 许可证

该项目遵循MIT许可证。