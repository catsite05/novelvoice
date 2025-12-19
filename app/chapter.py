import re
import os
from models import Novel, Chapter, db


def delete_novel(novel_id):
    # 获取小说对象
    novel = Novel.query.get_or_404(novel_id)
    
    # 删除与小说相关的所有章节
    Chapter.query.filter_by(novel_id=novel_id).delete()
    
    # 删除小说文件
    if os.path.exists(novel.file_path):
        os.remove(novel.file_path)
    
    # 删除数据库中的小说记录
    db.session.delete(novel)
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
        if (line.startswith('第') and ('章' in line or '节' in line)) or line.startswith('序章') or line.startswith('序言') or (line.startswith('序') and len(line) < 50):
            # Make sure it's not just a reference to a chapter title in the text
            # Chapter titles should be standalone lines or near the beginning of sections
            if i == 0 or (i > 0 and len(lines[i-1].strip()) == 0 and (i < 2 or len(lines[i-2].strip()) == 0)):
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
        if first_lines and (('章' in first_lines[0] and first_lines[0].startswith('第')) or first_lines[0].startswith('序')):
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
    if novel_id:
        chapters = Chapter.query.filter_by(novel_id=novel_id).all()
    else:
        chapters = Chapter.query.all()
    return {"chapters": [{"id": c.id, "title": c.title} for c in chapters]}

def list_novels():
    novels = Novel.query.all()
    return {"novels": [{"id": n.id, "title": n.title, "author": n.author, "upload_date": n.upload_date.isoformat() if n.upload_date else None} for n in novels]}

def get_chapter_content(novel_id, chapter_id):
    # Get the novel and chapter information
    novel = Novel.query.get_or_404(novel_id)
    chapter = Chapter.query.filter_by(id=chapter_id, novel_id=novel_id).first_or_404()
    
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
        start_position (int): 开始位置
        end_position (int, optional): 结束位置
        
    Returns:
        str: 章节内容
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 移动到章节开始位置
            f.seek(start_position)
            
            if end_position is not None:
                # 计算需要读取的字符数
                size = end_position - start_position
                content = f.read(size)
            else:
                # 读取到文件末尾
                content = f.read()
        return content
    except UnicodeDecodeError:
        # If we encounter a decode error, try reading with error handling
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            f.seek(start_position)
            if end_position is not None:
                size = end_position - start_position
                content = f.read(size)
            else:
                content = f.read()
        return content