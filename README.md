# pdf-to-video-app/pdf-to-video-app/README.md

# PDF to Video App

该项目是一个将PDF文件转换为讲解视频的应用程序。用户可以输入一个PDF文件，应用程序将提取其中的文本和图片，并生成一个引人注目的讲解视频。

## 项目结构

```
pdf-to-video-app
├── src
│   ├── main.py              # 应用程序入口点
│   ├── pdf_processor.py     # PDF处理模块
│   ├── video_creator.py     # 视频创建模块
│   ├── utils
│   │   └── helpers.py       # 辅助函数
│   └── types
│       └── index.py         # 类型和接口定义
├── requirements.txt         # 项目依赖
└── README.md                # 项目文档
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
   pip install -r requirements.txt
   conda install -c conda-forge tesserocr
   ```

请修改anaconda3\envs\paperagent\lib\site-packages\deepdoctection\extern\tessocr.py
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
   python src/main.py
   ```

   <!-- 替换 `<path_to_pdf>` 为你的PDF文件路径。 -->

## 贡献

欢迎任何形式的贡献！请提交问题或拉取请求。

## 许可证

该项目遵循MIT许可证。