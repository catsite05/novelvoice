from flask import request, jsonify, g
import os
import threading
from datetime import datetime
from models import Novel, Chapter, db
from chapter import split_novel_into_chapters
from audio_generator import preprocess_chapter_script

def upload_file(app):
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '未找到上传文件'}), 400

    # 必须登录，且只有当前登录用户作为小说所有者
    user = getattr(g, 'current_user', None)
    if user is None:
        return jsonify({'success': False, 'message': '未登录或登录已过期'}), 401
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'message': '未选择文件'}), 400
    
    if file and file.filename.endswith('.txt'):
        try:
            # Get novel title from filename (without extension)
            novel_title = os.path.splitext(file.filename)[0]
            
            # Generate unique filename to avoid conflicts
            filename = f"{novel_title}_{int(datetime.now().timestamp())}.txt"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            
            # Create a new Novel record
            new_novel = Novel(
                title=novel_title,
                author="Unknown",  # Could be extracted from file metadata or user input
                file_path=file_path,
                upload_date=datetime.now(),
                user_id=user.id,
            )
            
            db.session.add(new_novel)
            db.session.commit()
            
            # Split the novel into chapters
            chapters_count = split_novel_into_chapters(file_path, new_novel.id)
            
            # 启动后台线程为前10章的第一个分段生成配音脚本
            _start_preprocessing_threads(app, new_novel.id)
            
            return jsonify({
                'success': True, 
                'message': f'小说《{novel_title}》上传成功！已解析 {chapters_count} 个章节',
                'novel_id': new_novel.id,
                'novel_title': novel_title
            }), 200
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': f'上传失败：{str(e)}'}), 500
    
    return jsonify({'success': False, 'message': '不支持的文件格式，请上传.txt文件'}), 400


def _start_preprocessing_threads(app, novel_id):
    """
    启动后台线程为前10章的第一个分段生成配音脚本
    """
    def preprocess_worker():
        with app.app_context():
            # 获取前10章
            chapters = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.id).limit(10).all()
            
            for chapter in chapters:
                try:
                    print(f"[预处理] 开始为章节 {chapter.id} 生成第一个分段的配音脚本...")
                    preprocess_chapter_script(chapter.id)
                    print(f"[预处理] 章节 {chapter.id} 的第一个分段配音脚本生成完成")
                except Exception as e:
                    print(f"[预处理] 章节 {chapter.id} 预处理失败: {e}")
                    import traceback
                    traceback.print_exc()
    
    # 在后台线程中执行预处理
    thread = threading.Thread(target=preprocess_worker, daemon=True)
    thread.start()