# AGENTS.md

This file provides guidance to Qoder (qoder.com) when working with code in this repository.

## Project Overview
NovelVoice is a Flask-based web application that converts Chinese novel text files into audio books with character-aware voice synthesis. The system uses LLM to analyze text, identify characters and dialogue, then generates multi-voice audio using Azure TTS (via EasyVoice).

## Architecture

### Core Components
All Python modules are located in the `app/` directory:

1. **Flask App (`app/app.py`)**: Entry point that initializes the Flask application, database, authentication, and routes
2. **Database Models (`app/models.py`)**: SQLAlchemy models for User, Novel, Chapter, and Character entities
3. **Configuration (`app/config.py`)**: Application configuration including session settings and database paths
4. **File Upload (`app/upload.py`)**: Handles novel file uploads and creates Novel records
5. **Chapter Processing (`app/chapter.py`)**: Novel parsing and chapter segmentation logic
6. **Audio Generation (`app/audio.py`)**: Manages audio synthesis and streaming
7. **LLM Integration (`app/llm_client.py`)**: Connects to LLM API for voice script generation
8. **Voice Script Generation (`app/voice_script.py`)**: Converts LLM output to EasyVoice-compatible format
9. **EasyVoice Client (`app/easyvoice_client.py`)**: Interfaces with local EasyVoice TTS service

### Data Flow
1. User uploads a `.txt` novel file → `app/upload.py` saves it and creates Novel record
2. `split_novel_into_chapters()` parses the file using regex patterns to detect Chinese chapter markers (第X章, 序章, etc.)
3. When user plays a chapter → `app/audio.py` retrieves chapter content
4. Content is sent to LLM which analyzes characters and splits dialogue from narration → `app/llm_client.py`
5. `app/voice_script.py` converts LLM JSON output to EasyVoice format, mapping characters to Azure TTS voices from `voice.json`
6. `app/easyvoice_client.py` sends the script to local EasyVoice service (default: http://localhost:3000)
7. Generated MP3 is cached and streamed to the user

### Database Schema
- **User**: User authentication (username, password_hash, is_superuser)
- **Novel**: Stores uploaded novel metadata (title, author, file_path, upload_date, user_id FK)
- **Chapter**: Contains chapter metadata (title, start_position in file, audio_file_path, audio_status, novel_id FK)
- **Character**: Caches character info extracted by LLM (name, gender, personality, voice mapping)

### Voice Configuration
`voice.json` maps character traits to Azure TTS voice IDs:
- Gender: Male/Female
- Personalities: Warm, Lively, Passion, Sunshine, Professional, Reliable, Humorous, Bright
- Default narrator voice: zh-CN-YunxiNeural

## Development Commands

### Running the Application
```bash
source ./venv/bin/activate
python3 app/app.py
```
Application runs at http://localhost:5002 in debug mode.

For quick testing with environment variables set:
```bash
./test.sh
```

For deployment using Docker:
```bash
./deploy.sh
```

### Environment Variables
Required environment variables (see `test.sh` for example):
- `LLM_API_KEY`: API key for LLM service
- `LLM_BASE_URL`: Base URL for LLM API endpoint
- `LLM_MODEL`: Model identifier (e.g., "qwen3-max")
- `EASYVOICE_BASE_URL`: URL of local EasyVoice TTS service
- `SECRET_KEY`: Flask secret key for session management

### Database Initialization
Database is automatically created on first run via `db.create_all()` in `app/app.py`.
SQLite database file: `instance/novelvoice.db`

### Dependencies
Install via:
```bash
pip install -r requirements.txt
```
Core dependencies: Flask 2.3.3, Flask-SQLAlchemy 3.0.5, requests 2.31.0

## Key Implementation Details

### Authentication System
- Session-based authentication using Flask sessions
- User model with username/password_hash and is_superuser flag
- `@login_required` decorator protects routes, returns 401 for API requests or redirects to login for page requests
- Superuser-only admin panel at `/admin/users` for user management
- Create initial superuser with `create_superuser.py` script

### Chapter Detection Algorithm
The system uses multi-pattern regex matching in `split_novel_into_chapters()`:
- Detects lines starting with "第" + "章"/"节" 
- Handles special chapters: 序章, 序言, 序
- Validates chapter boundaries by checking for blank lines before/after
- Stores start position (byte offset) for efficient content extraction

### LLM Prompt Structure
`app/llm_client.py` sends a detailed prompt asking LLM to:
1. Extract character list with gender and personality traits
2. Segment text into narrator/dialogue parts
3. Recommend rate/volume/pitch parameters
4. Handle dialogue attribution markers (e.g., "XX道:", "XX说:")

The prompt includes specific rules for processing dialogue introductions (前导语).

### Audio Segmentation
Long chapters are split into ~1500 character segments at paragraph boundaries (`_split_content_into_segments()`) to avoid LLM token limits and improve processing reliability.

### Content Reading Optimization
`_read_chapter_content()` uses file seeking to read only the required chapter range, avoiding loading entire novels into memory.

### Async Audio Generation
- Audio generation runs in background threads to avoid blocking HTTP requests
- `/preprocess-chapter-script` endpoint starts background processing
- `/chapter-script-status` endpoint polls for completion status
- `/cancel-generation` endpoint allows cancellation of background tasks

## Important Notes
- All text files must be UTF-8 encoded Chinese novels
- Chapter titles must follow Chinese conventions (第X章 format)
- EasyVoice service must be running locally before audio generation
- Audio files are cached in the `audio/` directory after first generation
- The system automatically creates `uploads/` and `audio/` directories on startup
