# NovelVoice - 有声小说

NovelVoice是一个Web应用程序，能够将自动中文小说文本文件转换为高质量的有声书，并提供边转边播的在线播放功能。该系统使用LLM智能分析文本内容，识别角色和对话，并使用多声音合成技术，可以根据角色性别和性格特征分配不同的语音，生成逼真的有声书体验。适合与NAS等设备结合使用，实现无线上网播放。

目前已经实现的功能包括：

- 用户登录和创建（需超级管理员）
- 小说上传和解析（目前仅支持UTF8 txt格式）
- 个人小说库管理
- 章节自动分割和手动调整
- 为小说设置单独的LLM模型(不设置的话使用默认模型)
- 小说文本阅读，为移动端优化
- 实时音频生成和播放，支持后台播放、息屏播放、切换页面后保持播放
- 智能角色识别和语音分配，也可手动调整
- 支持从任一章节开始播放，也支持小说断点续播
- HLS推流（仅测试了iPhone和Edge浏览器，其中Edge浏览器有些小瑕疵）
- 管理员权限管理

TODO：

- 支持更多小说格式（如EPUB）
- 整体上优化页面
- 自动获取小说作者、简介等信息生成小说封面。
- 提供API接口，支持批量处理

iPhone上的限制：

- 如果进入后台播放，在切换下一章的时候（audio换源）会停止播放，必须要用户手动点一下才能继续。
- 切换页面的时候没办法自动播放，必须要用户手动点一下。

## 🌟 主要特性

- **智能文本分析**: 使用LLM自动识别小说中的角色、对话和叙述内容
- **多声音合成**: 根据角色特征（性别、性格等）分配不同的语音
- **实时音频生成**: 多线程音频生成管道，支持实时流媒体播放
- **自适应流媒体**: 基于HLS技术，支持断点续传和自适应播放
- **用户管理**: 支持用户注册、登录和个人小说库管理
- **章节分割**: 自动识别小说章节结构
- **缓存优化**: 音频文件缓存，支持重复播放

## 🏗️ 技术架构

### 核心技术栈
- **后端**: Flask 3.1.2 + SQLAlchemy
- **数据库**: SQLite (默认，可配置为其他数据库)
- **文本转语音**: Microsoft Edge TTS / Azure TTS (通过EasyVoice)
- **流媒体**: FFmpeg + HLS
- **AI服务**: 通义千问等LLM API

### 系统组件

```
app/
├── app.py              # Flask应用入口
├── models.py           # 数据库模型
├── config.py           # 应用配置
├── upload.py           # 文件上传处理
├── chapter.py          # 小说解析和章节分割
├── audio.py            # 音频API接口
├── audio_generator.py  # 核心音频生成引擎
├── llm_client.py       # LLM API客户端
├── voice_script.py     # 语音脚本生成
├── easyvoice_client.py # EasyVoice TTS客户端
├── edgetts_client.py   # Edge TTS客户端
└── hls_manager.py      # HLS流媒体管理
```

## 🚀 快速开始

### 环境要求

- Python 3.8+
- FFmpeg (必需，用于音频处理)
- 有效的LLM API密钥

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd novelvoice
```

2. **创建虚拟环境**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate     # Windows
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **安装系统依赖**
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

5. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，填入必要的配置
```

### 必需环境变量

```bash
# Flask配置
SECRET_KEY=your-secret-key-here

# LLM API配置
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-max


```

### 运行应用

**开发模式**
```bash
python3 app/app.py
```

**测试模式** (使用预配置的环境变量)
```bash
./test.sh
```

**Docker部署**
```bash
./deploy.sh # 如果部署到本地Docker容器，需要去配置SSH服务器那一行
```

访问地址: http://localhost:5002

## 📖 使用指南

### 1. 用户注册/登录
- 首次使用需要注册用户账户
- 支持管理员权限管理

### 2. 上传小说
- 支持 `.txt` 格式的中文小说文件
- 系统自动解析章节结构
- 支持作者信息录入

### 3. 音频生成
- 点击章节开始音频生成
- 系统自动分析角色和对话
- 根据角色特征选择合适的语音

### 4. 播放管理
- 支持在线播放
- 自动缓存生成的音频文件
- 支持断点续传和章节跳转

## 🔧 配置说明

### 语音配置
`voice.json` 文件包含角色特征到Azure TTS语音的映射：
- **性别**: 男声/女声
- **性格**: 温暖、活泼、热情、阳光、专业、可靠、幽默、明亮
- **默认旁白**: zh-CN-YunxiNeural

### 数据库配置
默认使用SQLite数据库 (`instance/novelvoice.db`)，可通过修改 `config.py` 配置其他数据库。

### 音频生成配置
- **分段长度**: 约1500字符为一个音频段落
- **多线程处理**: 3个并行线程处理音频生成
- **缓存策略**: 音频文件自动缓存，支持重复播放

## 📁 项目结构

```
novelvoice/
├── app/                    # 主要应用代码
│   ├── *.py               # 各种功能模块
├── templates/             # HTML模板
├── static/                # 静态文件 (CSS, JS, 图片)
├── uploads/               # 上传的小说文件
├── audio/                 # 生成的音频文件
├── hls_cache/             # HLS流媒体缓存
├── instance/              # 数据库文件
├── requirements.txt       # Python依赖
├── docker-compose.yml     # Docker编排配置
├── .env.example          # 环境变量示例
└── README.md             # 项目说明
```

## 🐳 Docker部署

使用Docker Compose快速部署：

```bash
docker-compose up -d
```

这将启动NovelVoice应用并自动配置数据持久化。


## 📋 API文档

### 音频播放接口
- `GET /audio/<novel_id>/<chapter_id>` - 获取音频播放信息
- `POST /api/generate_audio` - 生成章节音频
- `GET /api/chapter_status/<chapter_id>` - 查询生成状态

### 小说管理接口
- `POST /api/upload` - 上传小说文件
- `GET /api/novels` - 获取用户小说列表
- `GET /api/novels/<novel_id>/chapters` - 获取章节列表

## 🔍 故障排除

### 常见问题

1. **FFmpeg未安装**
   - 确保系统已安装FFmpeg
   - Ubuntu/Debian: `sudo apt-get install ffmpeg`
   - macOS: `brew install ffmpeg`

2. **LLM API调用失败**
   - 检查API密钥和网络连接
   - 确认API配额未超出限制

3. **音频生成失败**
   - 检查Edge TTS或EasyVoice服务状态
   - 确认voice.json配置文件正确

4. **数据库错误**
   - 确保instance目录有写入权限
   - 检查数据库文件是否损坏

### 日志调试
应用运行时会输出详细的日志信息，包括：
- 音频生成进度
- LLM API调用状态
- 数据库操作记录
- 文件上传处理信息

## 🤝 贡献指南

欢迎提交Issue和Pull Request来改进项目。

### 开发环境设置
1. Fork项目仓库
2. 创建开发分支
3. 进行代码修改
4. 测试功能完整性
5. 提交Pull Request

## 📄 许可证

本项目采用MIT许可证。详情请见LICENSE文件。不建议用于商业用途。

## 🙏 致谢

- Edge-TTS - 提供高质量的文本转语音服务（https://github.com/rany2/edge-tts）
- EasyVoice - 本项目借鉴了Kevin大大的思路和提示词（https://github.com/cosin2077/easyVoice）
- FFmpeg - 提供强大的音频处理功能
- Flask框架 - 提供简洁优雅的Web开发体验
---

**注意**: 请确保在使用前配置有效的LLM API密钥，并遵守相关的服务使用条款。