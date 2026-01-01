import re
import os
import shutil
from flask import g, abort
from models import Novel, Chapter, db


def delete_novel(novel_id):
    # 获取小说对象
    novel = Novel.query.get_or_404(novel_id)

    # 权限校验：普通用户只能删除自己的小说
    user = getattr(g, 'current_user', None)
    if user is None:
        abort(401)
    if not user.is_superuser and novel.user_id != user.id:
        abort(403)
    
    # 获取项目根目录
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    audio_folder = os.path.join(root_dir, 'audio')
    script_folder = os.path.join(audio_folder, 'script')
    
    # 删除与小说相关的所有章节及对应的音频文件和配音脚本
    chapters = Chapter.query.filter_by(novel_id=novel_id).all()
    for chapter in chapters:
        # 删除按默认路径命名的音频文件
        default_audio_path = os.path.join(audio_folder, f'chapter_{chapter.id}.mp3')
        if os.path.exists(default_audio_path):
            try:
                os.remove(default_audio_path)
                print(f"已删除默认路径音频文件: {default_audio_path}")
            except Exception as e:
                print(f"删除默认路径音频文件失败 {default_audio_path}: {e}")
        
        # 删除该章节的所有配音脚本文件
        if os.path.exists(script_folder):
            for script_file in os.listdir(script_folder):
                if script_file.startswith(f'chapter_{chapter.id}_segment_') and script_file.endswith('_script.json'):
                    script_path = os.path.join(script_folder, script_file)
                    try:
                        os.remove(script_path)
                        print(f"已删除配音脚本文件: {script_path}")
                    except Exception as e:
                        print(f"删除配音脚本文件失败 {script_path}: {e}")
    
    # 删除小说的专属音频文件夹
    novel_audio_folder = os.path.join(audio_folder, f'novel-{novel_id}')
    if os.path.exists(novel_audio_folder):
        try:
            shutil.rmtree(novel_audio_folder)
            print(f"已删除小说音频文件夹: {novel_audio_folder}")
        except Exception as e:
            print(f"删除小说音频文件夹失败 {novel_audio_folder}: {e}")
    
    # 删除小说的专属脚本文件夹
    novel_script_folder = os.path.join(script_folder, f'novel-{novel_id}')
    if os.path.exists(novel_script_folder):
        try:
            shutil.rmtree(novel_script_folder)
            print(f"已删除小说脚本文件夹: {novel_script_folder}")
        except Exception as e:
            print(f"删除小说脚本文件夹失败 {novel_script_folder}: {e}")
    
    # 删除章节记录
    Chapter.query.filter_by(novel_id=novel_id).delete()
    
    # 删除该小说的所有音频进度记录
    from models import AudioProgress
    AudioProgress.query.filter_by(novel_id=novel_id).delete()
    
    # 删除该小说的所有角色记录
    from models import Character
    Character.query.filter_by(novel_id=novel_id).delete()
    
    # 删除小说文件
    if os.path.exists(novel.file_path):
        try:
            os.remove(novel.file_path)
            print(f"已删除小说文件: {novel.file_path}")
        except Exception as e:
            print(f"删除小说文件失败 {novel.file_path}: {e}")
    
    # 删除数据库中的小说记录
    db.session.delete(novel)
    db.session.commit()
    
    return True


def delete_chapter(chapter_id):
    # 获取章节对象
    chapter = Chapter.query.get_or_404(chapter_id)
    
    # 获取小说对象以进行权限检查
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    # 权限校验：普通用户只能删除自己小说下的章节
    user = getattr(g, 'current_user', None)
    if user is None:
        abort(401)
    if not user.is_superuser and novel.user_id != user.id:
        abort(403)
    
    # 获取项目根目录
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    audio_folder = os.path.join(root_dir, 'audio')
    script_folder = os.path.join(audio_folder, 'script')
    
    # 删除该章节的音频文件
    default_audio_path = os.path.join(audio_folder, f'chapter_{chapter.id}.mp3')
    if os.path.exists(default_audio_path):
        try:
            os.remove(default_audio_path)
            print(f"已删除音频文件: {default_audio_path}")
        except Exception as e:
            print(f"删除音频文件失败 {default_audio_path}: {e}")
    
    # 删除该章节的所有配音脚本文件
    if os.path.exists(script_folder):
        for script_file in os.listdir(script_folder):
            if script_file.startswith(f'chapter_{chapter.id}_segment_') and script_file.endswith('_script.json'):
                script_path = os.path.join(script_folder, script_file)
                try:
                    os.remove(script_path)
                    print(f"已删除配音脚本文件: {script_path}")
                except Exception as e:
                    print(f"删除配音脚本文件失败 {script_path}: {e}")
    
    # 删除数据库中的章节记录
    db.session.delete(chapter)
    db.session.commit()
    
    return True


def split_novel_into_chapters(file_path, novel_id):
    # Read the uploaded novel
    with open(file_path, 'r', encoding='utf-8') as novel_file:
        novel_content = novel_file.read()
    
    # Split the novel into chapters based on Chinese chapter patterns
    # More precise regex for Chinese chapter titles - match titles at start of line
    # We need to match the actual start of chapters, not just any occurrence of chapter titles
    chapter_positions = []
    chapter_titles = []
    
    # First, find all potential chapter titles
    lines = novel_content.split('\n')
    for i, line in enumerate(lines):
        line = line.strip()
        # Check if this line looks like a chapter title
        if (line.startswith('第') and ('章' in line or '节' in line or '卷' in line or '回' in line)) or line.startswith('序章') or line.startswith('序言') or (line.startswith('序') and len(line) < 50):
            # Calculate the actual position in the original text
            # We need to calculate the position correctly by counting characters and newlines
            position = 0
            for j in range(i):
                position += len(lines[j]) + 1  # +1 for newline character
            chapter_positions.append(position)
            chapter_titles.append(line)
    
    # Handle the case where the first chapter starts at the beginning of the file
    if not chapter_positions or chapter_positions[0] > 100:
        # Check if the file starts with what looks like a chapter
        first_lines = novel_content[:100].split('\n')
        if first_lines and ((('章' in first_lines[0] or '卷' in first_lines[0] or '回' in first_lines[0] or '节' in first_lines[0]) and first_lines[0].startswith('第')) or first_lines[0].startswith('序')):
            chapter_positions.insert(0, 0)
            chapter_titles.insert(0, first_lines[0].strip())
    
    # Create chapter data structures
    chapters = []
    positions = []
    for title, pos in zip(chapter_titles, chapter_positions):
        chapters.append({'title': title})
        positions.append(pos)
    
    # If no chapters found with patterns, split by "\n\n" (paragraphs)
    if not chapters:
        paragraphs = novel_content.split('\n\n')
        # Assume every 20 paragraphs is a chapter
        for i in range(0, len(paragraphs), 20):
            chapter_content = '\n\n'.join(paragraphs[i:i+20])
            # Extract title from chapter content (first non-empty line)
            lines = [line.strip() for line in chapter_content.split('\n') if line.strip()]
            chapter_title = lines[0][:50] + "..." if lines and len(lines[0]) > 50 else lines[0] if lines else f"章节 {i//20 + 1}"
            
            chapters.append({
                'title': chapter_title,
                'content': chapter_content
            })
            positions.append(i*20)  # Approximate position
    
    # Also check for the very first chapter that might start at the beginning of the file
    intro_pattern = r'(^(\s*序\s*章|\s*序\s*言|\s*序).*?)(?=\n\s*第|$)'
    intro_match = re.search(intro_pattern, novel_content, re.DOTALL)
    if intro_match:
        intro_content = intro_match.group(0).strip()
        lines = intro_content.strip().split('\n')
        intro_title = lines[0].strip() if lines else "序章"
        
        # Check if we already have this chapter
        has_intro = any(chapter['title'] == intro_title for chapter in chapters)
        
        # Insert at the beginning if not already present
        if not has_intro:
            chapters.insert(0, {
                'title': intro_title,
                'content': intro_content
            })
            positions.insert(0, intro_match.start())
            intro_added = True
    
    # Save chapter information to database
    for i, (chapter_data, position) in enumerate(zip(chapters, positions)):
        # Create a new Chapter record
        new_chapter = Chapter(
            title=chapter_data['title'],
            start_position=position,
            audio_file_path=None,  # No audio file yet
            novel_id=novel_id  # Link to the novel
        )
        
        db.session.add(new_chapter)
    
    db.session.commit()
    
    # Return the number of chapters created
    return len(chapters)

def list_chapters(novel_id=None):
    user = getattr(g, 'current_user', None)
    if user is None:
        abort(401)

    query = Chapter.query
    if novel_id:
        query = query.filter_by(novel_id=novel_id)

    # 普通用户只能看到自己小说下的章节
    if not user.is_superuser:
        query = query.join(Novel).filter(Novel.user_id == user.id)

    chapters = query.all()
    return {"chapters": [{"id": c.id, "title": c.title} for c in chapters]}

def list_novels():
    user = getattr(g, 'current_user', None)
    if user is None:
        abort(401)

    if user.is_superuser:
        novels = Novel.query.all()
    else:
        novels = Novel.query.filter_by(user_id=user.id).all()

    return {"novels": [
        {
            "id": n.id,
            "title": n.title,
            "author": n.author,
            "upload_date": n.upload_date.isoformat() if n.upload_date else None,
            "last_read_chapter_id": n.last_read_chapter_id
        } for n in novels
    ]}

def get_chapter_content(novel_id, chapter_id):
    # Get the novel and chapter information
    novel = Novel.query.get_or_404(novel_id)
    chapter = Chapter.query.filter_by(id=chapter_id, novel_id=novel_id).first_or_404()

    # 权限校验：仅在有登录用户时检查（HTTP 请求由 @login_required 保证已登录）
    user = getattr(g, 'current_user', None)
    if user is not None:
        if not user.is_superuser and novel.user_id != user.id:
            abort(403)
    
    # Get all chapters for this novel ordered by position
    all_chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.start_position).all()
    
    # Find the current chapter index
    current_index = next((i for i, ch in enumerate(all_chapters) if ch.id == chapter_id), -1)
    
    if current_index == -1:
        return None
    
    # Calculate the end position (next chapter's start position or end of file)
    if current_index < len(all_chapters) - 1:
        end_position = all_chapters[current_index + 1].start_position
    else:
        end_position = None  # Will read until EOF
    
    # Extract chapter content using streaming read to avoid loading entire file
    try:
        chapter_content = _read_chapter_content(novel.file_path, chapter.start_position, end_position)
    except Exception as e:
        # If we have an end position, try reading with a slightly adjusted end position
        if end_position is not None:
            try:
                # Try with a slightly adjusted end position
                adjusted_end = max(end_position - 10, chapter.start_position + 1)
                chapter_content = _read_chapter_content(novel.file_path, chapter.start_position, adjusted_end)
            except:
                # If that fails, try reading from start to end without specific end position
                try:
                    chapter_content = _read_chapter_content(novel.file_path, chapter.start_position, None)
                except:
                    # If all else fails, return an empty content
                    chapter_content = ""
        else:
            # If all else fails, return an empty content
            chapter_content = ""
        
    # Clean up the content (remove leading/trailing whitespace and normalize newlines)
    chapter_content = chapter_content.strip()
        
    return {
        "title": chapter.title,
        "content": chapter_content
    }

def _read_chapter_content(file_path, start_position, end_position=None):
    """
    从文件中读取章节内容，避免一次性加载整个文件
    
    Args:
        file_path (str): 文件路径
        start_position (int): 开始位置（字符位置）
        end_position (int, optional): 结束位置（字符位置）
        
    Returns:
        str: 章节内容
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 读取整个文件内容
            content = f.read()
            
            # 使用字符位置进行切片
            if end_position is not None:
                chapter_content = content[start_position:end_position]
            else:
                chapter_content = content[start_position:]
        
        return chapter_content
    except UnicodeDecodeError:
        # If we encounter a decode error, try reading with error handling
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            
            if end_position is not None:
                chapter_content = content[start_position:end_position]
            else:
                chapter_content = content[start_position:]
        
        return chapter_content