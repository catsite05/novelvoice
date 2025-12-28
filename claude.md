# NovelVoice - Claude Code Project Guide

This file provides comprehensive guidance to Claude Code when working with this repository.

## Project Overview

**NovelVoice** is a Flask-based web application that converts Chinese novel text files into multi-voice audio books. The system intelligently analyzes text using LLM to identify characters and dialogue, then generates professional audio with character-specific voices using Azure TTS (via Edge TTS or EasyVoice).

### Key Features
- 📚 Chinese novel text file upload and automatic chapter detection
- 🤖 LLM-powered script generation with character and dialogue identification
- 🎭 Multi-character voice synthesis with personality-based voice mapping
- 🎵 Real-time audio streaming with HLS adaptive streaming support
- 👥 Multi-user authentication and authorization
- 📱 iOS Safari compatible with responsive design
- ⚡ Three-threaded architecture for concurrent script generation, TTS synthesis, and HLS conversion
- 🔧 Flexible LLM configuration (global and per-novel settings)

## Architecture

### Technology Stack

**Backend:**
- Flask 2.3.3 (Web framework)
- SQLAlchemy 3.0.5 + SQLite (Database)
- Flask Session + Werkzeug (Authentication)
- Edge TTS 6.1.18 (Primary TTS engine)
- ffmpeg-python 0.2.0 (Audio processing and HLS conversion)
- requests 2.31.0 (HTTP client for LLM API)

**Frontend:**
- HTML5 + CSS3 + JavaScript
- HLS.js (HLS playback for non-iOS devices)
- Global audio player component (906 lines, cross-page state management)

**Integration:**
- OpenAI-compatible LLM API (default: Alibaba Qwen3-Max)
- Azure TTS via Edge TTS (default) or EasyVoice (optional local proxy)

### Directory Structure

```
novelvoice/
├── app/                          # Backend application core
│   ├── app.py                    # Flask app entry point (493 lines)
│   ├── models.py                 # SQLAlchemy models (58 lines)
│   │   ├── User                  # User authentication
│   │   ├── Novel                 # Novel metadata and LLM config
│   │   ├── Chapter               # Chapter metadata and audio status
│   │   └── Character             # Character voice mapping cache
│   ├── config.py                 # Flask configuration (36 lines)
│   ├── upload.py                 # File upload handler (84 lines)
│   ├── chapter.py                # Chapter parsing and management (281 lines)
│   ├── audio.py                  # Audio streaming endpoints (249 lines)
│   ├── audio_generator.py        # Audio generation engine (650 lines) ⭐ Core module
│   ├── llm_client.py             # LLM API client (237 lines)
│   ├── voice_script.py           # Voice script processing (146 lines)
│   ├── edgetts_client.py         # Edge TTS client (199 lines)
│   ├── easyvoice_client.py       # EasyVoice client (158 lines)
│   └── hls_manager.py            # HLS conversion manager (479 lines)
│
├── templates/                    # HTML templates
│   ├── base.html                 # Base template with global player
│   ├── login.html                # Login page
│   ├── admin_users.html          # User management (superuser only)
│   ├── novels.html               # Novel list page
│   ├── player.html               # Audio player page
│   ├── reader.html               # Text reader page
│   └── toc.html                  # Table of contents
│
├── static/js/
│   └── global-player.js          # Global audio player (906 lines)
│
├── voice.json                    # Character → Voice mapping configuration
├── instance/
│   └── novelvoice.db             # SQLite database
├── uploads/                      # Uploaded novel files
├── audio/                        # Generated MP3 files
│   └── script/                   # Cached voice scripts (JSON)
├── hls_cache/                    # HLS segment files
│   └── user_*/                   # User-isolated HLS cache
│
├── docker-compose.yml            # Docker orchestration
├── Dockerfile                    # Docker image build
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment variables example
├── test.sh                       # Local test script
├── create_superuser.py           # Create superuser utility
└── deploy.sh                     # Deployment script
```

## Core Data Flow

```
User uploads novel.txt
    ↓
[upload.py] Save file, create Novel record
    ↓
[chapter.py] Regex detect Chinese chapter markers (第X章, 序章, etc.)
    ↓
Background thread: Preprocess scripts for first 10 chapters
    ↓
User clicks play
    ↓
[audio_generator.py] - Three-threaded pipeline:

┌─────────────────────────────────────┐
│ Thread 1: Script Generation          │
├─────────────────────────────────────┤
│ - Read chapter content               │
│ - Split into ~1500 char segments     │
│ - Call LLM → [llm_client.py]         │
│ - Convert script → [voice_script.py] │
│ - Put in queue                       │
└─────────────────────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ Thread 2: Audio Synthesis            │
├─────────────────────────────────────┤
│ - Consume script queue               │
│ - Call TTS:                          │
│   - Edge TTS (default)               │
│   - or EasyVoice (optional)          │
│ - Write MP3 file incrementally       │
└─────────────────────────────────────┘
                ↓
┌─────────────────────────────────────┐
│ Thread 3: HLS Conversion             │
├─────────────────────────────────────┤
│ - Monitor MP3 file growth            │
│ - FFmpeg incremental MP3→HLS         │
│ - Generate playlist.m3u8 + .ts files │
└─────────────────────────────────────┘
    ↓
[audio.py] + [hls_manager.py] serve to client
    ↓
Frontend player [global-player.js]
- iOS: Native HLS playback
- Others: HLS.js or traditional streaming
```

## Database Schema

### User Table
- `id`: Primary key
- `username`: Unique username
- `password_hash`: Hashed password (Werkzeug)
- `is_superuser`: Boolean flag for admin privileges

### Novel Table
- `id`: Primary key
- `title`: Novel title
- `author`: Author name
- `file_path`: Path to uploaded .txt file
- `upload_date`: Timestamp
- `user_id`: Foreign key to User
- `llm_api_key`, `llm_base_url`, `llm_model`: Novel-specific LLM config (optional)

### Chapter Table
- `id`: Primary key
- `title`: Chapter title (e.g., "第一章")
- `start_position`: Byte offset in novel file
- `audio_file_path`: Path to generated MP3
- `audio_status`: Generation status
- `novel_id`: Foreign key to Novel

### Character Table
- `id`: Primary key
- `name`: Character name
- `gender`: Male/Female
- `personality`: Personality trait
- `voice`: Azure TTS voice ID
- `novel_id`: Foreign key to Novel

## Key Implementation Details

### 1. Chapter Detection Algorithm

[chapter.py:split_novel_into_chapters()](app/chapter.py)

Uses multi-pattern regex matching:
- Detects lines starting with "第" + number + "章"/"节"
- Handles special chapters: 序章, 序言, 序
- Validates with blank line checks before/after
- Stores byte offset (`start_position`) for efficient content extraction

Example patterns:
```
第一章 标题
第001章 标题
序章
序言
```

### 2. LLM Integration

[llm_client.py](app/llm_client.py)

- Sends structured prompt to LLM requesting:
  1. Character list with gender and personality
  2. Text segmentation (narrator vs. dialogue)
  3. Voice parameter recommendations (rate, pitch, volume)
  4. Dialogue attribution (e.g., "张三说:", "李四道:")

- Supports global LLM config (from environment variables)
- Supports novel-specific LLM config (overrides global settings)
- Returns JSON response following defined schema

### 3. Voice Mapping System

[voice.json](voice.json) + [voice_script.py](app/voice_script.py)

Maps character traits → Azure TTS voices:
```json
{
  "Male": {
    "Warm": "zh-CN-YunxiNeural",
    "Lively": "zh-CN-YunjianNeural",
    ...
  },
  "Female": {
    "Warm": "zh-CN-XiaoxiaoNeural",
    "Lively": "zh-CN-XiaoyiNeural",
    ...
  },
  "Narrator": "zh-CN-YunxiNeural"
}
```

`voice_script.py` converts LLM output to TTS-compatible format.

### 4. Audio Generation Engine

[audio_generator.py](app/audio_generator.py) - **Core module (650 lines)**

**GenerationManager:**
- Enforces one-generation-per-user limit
- Automatically cancels old tasks when new ones start
- Thread-safe with locks and queues

**Three-threaded Pipeline:**

**Thread 1: Script Generator**
- Splits chapter into ~1500 char segments (at paragraph boundaries)
- Calls LLM for each segment
- Converts to voice script format
- Puts scripts in queue

**Thread 2: Audio Producer**
- Consumes script queue
- Calls TTS API (Edge TTS or EasyVoice)
- Writes MP3 chunks to file
- Signals completion

**Thread 3: HLS Converter** ([hls_manager.py](app/hls_manager.py))
- Monitors MP3 file size
- Incrementally converts to HLS using FFmpeg
- Generates playlist.m3u8 + segment_*.ts files
- Enables playback before full generation completes

### 5. Authentication System

[app.py:login_required()](app/app.py)

- Session-based authentication (Flask sessions)
- `@login_required` decorator protects routes
- Returns 401 for JSON requests, redirects to login for page requests
- Superuser flag for admin privileges

**Authorization:**
- Superusers: Access all novels and user management
- Regular users: Access only their own novels

### 6. HLS Streaming

[hls_manager.py](app/hls_manager.py)

- Converts MP3 → HLS (MPEG-TS segments + playlist.m3u8)
- Incremental conversion: Creates segments while MP3 is still being generated
- User-isolated cache directories (hls_cache/user_<id>/)
- FFmpeg-based conversion with segment duration control
- Automatic cleanup of old segments

**Endpoints:**
- `/hls/<chapter_id>/stream` - Returns playlist.m3u8
- `/hls/<chapter_id>/<filename>` - Returns segment files (.ts)

### 7. Global Audio Player

[static/js/global-player.js](static/js/global-player.js) - 906 lines

Features:
- Cross-page state persistence
- HLS.js integration for non-iOS devices
- Native HLS for iOS Safari
- Playback speed control
- Progress tracking and saving
- Mini-player and expanded player modes
- Keyboard shortcuts

### 8. Content Optimization

**Preprocessing:**
- After upload, automatically preprocesses first 10 chapters' first segment
- Speeds up initial playback experience

**Memory Efficiency:**
- Uses file seeking (`_read_chapter_content()`) to read only required chapter range
- Avoids loading entire novel into memory

**Caching:**
- Voice scripts cached in `audio/script/chapter_<id>_segment_<n>.json`
- Enables fast regeneration without re-calling LLM

## REST API Endpoints

### Authentication
- `POST /login` - User login
- `POST /logout` - User logout
- `GET /admin/users` - User management page (superuser only)
- `POST /admin/users` - Create/delete users (superuser only)

### Novel Management
- `POST /upload` - Upload novel file
- `GET /novels` - Get user's novel list (JSON)
- `POST /novels/<id>/delete` - Delete novel
- `GET /novels/<id>/llm-config` - Get novel LLM config (JSON)
- `POST /novels/<id>/llm-config` - Update novel LLM config (JSON)

### Chapter Management
- `GET /chapters?novel_id=<id>` - Get chapter list (JSON)
- `GET /chapter-content?chapter_id=<id>` - Get chapter text content (JSON)

### Audio Generation & Streaming
- `POST /preprocess-chapter-script` - Start background script generation
- `GET /chapter-script-status?chapter_id=<id>` - Poll generation progress (JSON)
- `POST /cancel-generation/<chapter_id>` - Cancel generation task
- `GET /stream/<chapter_id>` - Traditional streaming endpoint
- `GET /hls/<chapter_id>/stream` - HLS playlist endpoint
- `GET /hls/<chapter_id>/<filename>` - HLS segment endpoint

### Progress Tracking
- `POST /update-reading-progress` - Save reading progress
- `GET /get-reading-progress/<novel_id>` - Get reading progress (JSON)

## Development Workflow

### Local Development

```bash
# Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure environment (copy .env.example to .env and edit)
cp .env.example .env
# Edit .env with your API keys

# Run application
python3 app/app.py
# Or use test script with inline env vars
./test.sh
```

Application runs at http://localhost:5002

### Docker Deployment

```bash
# Build and run
./deploy.sh
# Or manually
docker-compose up --build
```

### Create Initial Superuser

```bash
python3 create_superuser.py
```

### Testing HLS Functionality

```bash
python3 test_hls.py
```

## Environment Variables

Required in `.env` file:

```bash
# LLM Configuration (Global defaults)
LLM_API_KEY=your_api_key_here
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen3-max

# TTS Configuration
USE_EASYVOICE=0                    # 0 = Edge TTS (default), 1 = EasyVoice
EASYVOICE_BASE_URL=http://localhost:3000  # Only needed if USE_EASYVOICE=1

# Flask Configuration
SECRET_KEY=your_secret_key_here
```

**Novel-specific LLM config** (optional, overrides global):
- Can be set per-novel via `/novels/<id>/llm-config` API
- Stored in Novel table: `llm_api_key`, `llm_base_url`, `llm_model`
- Useful for different novels requiring different LLM providers or models

## System Dependencies

**Required:**
- Python 3.12+
- FFmpeg (for HLS conversion)

Install FFmpeg:
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg
```

## Important Notes for Development

### File Format Requirements
- All text files must be UTF-8 encoded
- Chinese novel format expected
- Chapter titles must follow Chinese conventions:
  - 第一章, 第001章
  - 序章, 序言, 序

### Code Style Guidelines
- Follow Flask best practices
- Use SQLAlchemy ORM for database operations
- Keep routes in `app.py`, business logic in separate modules
- Add docstrings to complex functions
- Use type hints where beneficial

### Common Tasks

**Adding a new route:**
1. Add route decorator in [app.py](app/app.py)
2. Implement handler function
3. Add `@login_required` if authentication needed
4. Check user permissions (user_id ownership or superuser)

**Adding a new TTS provider:**
1. Create new client module in `app/` (e.g., `app/newtts_client.py`)
2. Implement `generate_audio()` function matching signature
3. Add environment variable for selection (e.g., `USE_NEWTTS`)
4. Update [audio_generator.py](app/audio_generator.py) to import and use new client

**Modifying LLM prompt:**
1. Edit [llm_client.py:generate_voice_script()](app/llm_client.py)
2. Update prompt string
3. Test with various chapter content
4. Verify JSON response format remains compatible

**Changing voice mapping:**
1. Edit [voice.json](voice.json)
2. Add/modify gender → personality → voice_id mappings
3. Restart application to load new mappings

### Debugging Tips

**Check logs:**
- Flask debug logs show request/response info
- Look for exceptions in script generation, TTS calls, FFmpeg conversion

**Common issues:**

1. **Chapter detection fails:**
   - Check novel file encoding (must be UTF-8)
   - Verify chapter title format matches regex patterns
   - Add debug prints in `split_novel_into_chapters()`

2. **LLM returns invalid JSON:**
   - Check [llm_client.py](app/llm_client.py) prompt
   - Verify LLM API credentials
   - Test with shorter content segments

3. **TTS generation fails:**
   - If using Edge TTS: Check internet connection, Edge TTS may be rate-limited
   - If using EasyVoice: Verify `EASYVOICE_BASE_URL` is correct and service is running
   - Check voice ID exists in Azure TTS

4. **HLS playback issues:**
   - Verify FFmpeg is installed: `ffmpeg -version`
   - Check [hls_manager.py](app/hls_manager.py) logs for FFmpeg errors
   - Test with [test_hls.py](test_hls.py)

5. **Permission errors:**
   - Check `user_id` matches novel owner
   - Verify `is_superuser` flag for admin operations
   - Review `@login_required` decorator logic

### Git Workflow

Recent changes (from git log):
- 2025-12-27: Added novel-specific LLM configuration
- 2025-12-26: Added HLS streaming support
- 2025-12-23: Switched to Edge TTS as default provider

When making commits:
- Use clear, descriptive commit messages
- Reference issue numbers if applicable
- Keep commits focused on single feature/fix

## Architecture Decisions

### Why Three-Threaded Pipeline?
- **Parallelism**: LLM calls, TTS synthesis, FFmpeg conversion run concurrently
- **Early playback**: Client can start playing before full chapter completes
- **Resource efficiency**: Each thread optimized for I/O-bound (LLM, TTS) or CPU-bound (FFmpeg)

### Why SQLite?
- Single-file database, easy deployment
- Sufficient for typical load (< 100 concurrent users)
- No separate database server needed
- Can migrate to PostgreSQL/MySQL if needed

### Why Edge TTS as Default?
- No local service required (unlike EasyVoice)
- Free and accessible
- Good quality Chinese voices
- Streaming support reduces latency

### Why HLS over Traditional Streaming?
- iOS Safari requires HLS for adaptive streaming
- Better mobile experience with network fluctuations
- Incremental conversion enables early playback
- Standard format with broad compatibility

### Why Flask over FastAPI?
- Simpler synchronous code for complex multi-threaded generation
- Mature ecosystem with Flask-SQLAlchemy
- Session management built-in
- Sufficient performance for this use case

## Security Considerations

### Authentication
- Passwords hashed with Werkzeug's `generate_password_hash()`
- Flask sessions signed with `SECRET_KEY`
- CSRF protection via session tokens

### File Upload
- File extension validation (`.txt` only)
- Unique filename generation to prevent overwrites
- Files stored outside web root

### Authorization
- All novel/chapter access checks user ownership
- Superuser flag for admin operations only
- No path traversal in file serving (use database IDs)

### API Security
- Rate limiting recommended for production (not implemented)
- LLM API keys stored in environment variables (not in code)
- Novel-specific API keys encrypted in database (recommended for production)

## Performance Optimization

### Caching Strategy
- Voice scripts cached to avoid re-calling LLM
- HLS segments cached per user
- Chapter metadata cached in database

### Concurrency
- GenerationManager limits to 1 generation per user
- Prevents resource exhaustion
- SQLite WAL mode for better concurrent reads

### Memory Management
- File seeking for chapter content (avoids loading full novel)
- Streaming audio generation (no full chapter in memory)
- Incremental HLS conversion (processes chunks, not full file)

## Future Enhancement Ideas

1. **Redis caching** for voice scripts and HLS segments
2. **Background job queue** (Celery) for preprocessing
3. **WebSocket** for real-time generation progress
4. **CDN integration** for audio file serving
5. **Advanced chapter detection** using ML models
6. **Multi-language support** (English, Japanese novels)
7. **Custom voice training** integration
8. **Collaborative annotations** on reader page
9. **Audio quality settings** (bitrate selection)
10. **Batch upload** for multiple novels

## Related Documentation

- [AGENTS.md](AGENTS.md) - Original architecture guide (for Qoder)
- [HLS_IMPLEMENTATION.md](HLS_IMPLEMENTATION.md) - HLS technical details
- [GLOBAL_PLAYER.md](GLOBAL_PLAYER.md) - Global player architecture
- [TEST_IOS_SAFARI.md](TEST_IOS_SAFARI.md) - iOS testing guide

## Quick Reference

### Key Files to Know
- [app/app.py:493](app/app.py) - Flask routes and app initialization
- [app/audio_generator.py:650](app/audio_generator.py) - Core generation engine ⭐
- [app/llm_client.py:237](app/llm_client.py) - LLM integration
- [app/hls_manager.py:479](app/hls_manager.py) - HLS conversion
- [app/models.py:58](app/models.py) - Database schema
- [static/js/global-player.js:906](static/js/global-player.js) - Frontend player

### Essential Commands
```bash
# Start development server
python3 app/app.py

# Create superuser
python3 create_superuser.py

# Deploy with Docker
./deploy.sh

# Test HLS
python3 test_hls.py
```

### Database Queries (via Flask shell)
```python
from app.app import app, db
from app.models import User, Novel, Chapter, Character

with app.app_context():
    # List all users
    users = User.query.all()

    # Get novel with chapters
    novel = Novel.query.filter_by(id=1).first()
    chapters = novel.chapters

    # Find character by name
    char = Character.query.filter_by(name="张三").first()
```

---

**Version:** Based on codebase as of 2025-12-28
**Maintained for:** Claude Code and human developers
