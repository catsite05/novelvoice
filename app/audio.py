import os
import tempfile
import shutil
from flask import send_file, Response
from models import Novel, Chapter, db
from chapter import get_chapter_content
from voice_script import generate_voice_script
from easyvoice_client import EasyVoiceClient

def play_chapter(app, chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    
    # Check if audio file already exists
    if chapter.audio_file_path and os.path.exists(chapter.audio_file_path):
        return send_file(chapter.audio_file_path)
    
    # Get the novel associated with this chapter
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    # Get chapter content using the improved method
    from app.chapter import get_chapter_content
    try:
        chapter_data = get_chapter_content(novel.id, chapter_id)
        chapter_content = chapter_data['content'] if chapter_data else ""
    except Exception as e:
        print(f"获取章节内容时发生错误: {str(e)}")
        chapter_content = ""
    
    # Split content into segments of approximately 1500 characters
    # Each segment should end at a natural paragraph break
    segments = _split_content_into_segments(chapter_content, max_length=1500)
    
    # Generate audio file using easyvoice with voice script
    audio_filename = f"chapter_{chapter_id}.mp3"
    audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
    
    # Generate audio for each segment and concatenate
    _generate_audio_for_segments(segments, audio_path)
    
    # Update chapter record with audio file path
    chapter.audio_file_path = audio_path
    db.session.commit()
    
    return send_file(audio_path)

def _split_content_into_segments(content, max_length=1500):
    """
    将内容分割成段落，使用阶梯式分段策略以提高启动速度：
    - 第一个分段：约200字（快速启动）
    - 第二个分段：约400字（渐进加载）
    - 后续分段：约1500字（正常处理）
    所有分段都在自然段落边界处截断
    
    Args:
        content (str): 要分割的内容
        max_length (int): 后续段落的最大长度（默认1500）
    
    Returns:
        list: 分割后的段落列表
    """
    if not content or not content.strip():
        return []
    
    segments = []
    
    # 按单个换行符分割段落（更细粒度）
    paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
    
    if not paragraphs:
        return []
    
    # 阶梯式目标长度：第一段200，第二段400，后续1500
    target_lengths = [200, 400]  # 前两段的目标长度
    default_length = max_length  # 后续段落的目标长度
    
    current_segment = ""
    segment_index = 0  # 当前正在构建的段落索引
    
    for paragraph in paragraphs:
        # 计算加入当前段落后的总长度
        if current_segment:
            potential_length = len(current_segment) + len(paragraph) + 1  # +1 for \n
        else:
            potential_length = len(paragraph)
        
        # 确定当前段落的目标长度
        if segment_index < len(target_lengths):
            current_target = target_lengths[segment_index]
            min_length = int(current_target * 0.7)  # 最小长度为目标的70%
            max_target = int(current_target * 1.3)  # 最大长度为目标的130%
        else:
            current_target = default_length
            min_length = 200  # 后续段落最小200字
            max_target = default_length
        
        # 判断是否应该结束当前段落
        should_finish = False
        
        # 如果加上当前段落会超过最大目标长度
        if potential_length > max_target and current_segment:
            # 检查当前积累的内容是否达到最小长度
            if len(current_segment) >= min_length:
                should_finish = True
            else:
                # 如果当前段太短，继续添加
                current_segment += "\n" + paragraph if current_segment else paragraph
        # 如果当前长度已经接近目标，且加上下一段会超过目标的130%
        elif len(current_segment) >= min_length and potential_length > current_target:
            should_finish = True
        else:
            # 没有超过最大长度，继续添加
            current_segment += "\n" + paragraph if current_segment else paragraph
        
        # 完成当前段落
        if should_finish:
            segments.append(current_segment)
            current_segment = paragraph
            segment_index += 1
    
    # 添加最后一个段落
    if current_segment:
        # 如果最后一个段落太短（少于100字），且已经有之前的段落，尝试合并到上一个段落
        if len(current_segment) < 100 and segments:
            # 合并到上一个段落
            last_segment = segments.pop()
            merged = last_segment + "\n" + current_segment
            segments.append(merged)
        else:
            segments.append(current_segment)
    
    # 如果没有任何段落，返回原内容
    if not segments:
        segments = [content.strip()]
    
    # 调试输出：显示每段的长度
    print(f"\n分段统计（共{len(segments)}段）：")
    for i, seg in enumerate(segments):
        print(f"  第{i+1}段: {len(seg)}字")
    print()
    
    return segments

def _generate_audio_for_segments(segments, output_path):
    """
    为每个段落生成音频并连接成一个完整的音频文件
    
    Args:
        segments (list): 段落列表
        output_path (str): 输出音频文件路径
    """
    # 直接在AUDIO_FOLDER中生成段落音频文件
    segment_files = []
    
    # 获取输出文件的基础名称（不含扩展名）用于生成段落文件名
    output_basename = os.path.splitext(os.path.basename(output_path))[0]
    output_dir = os.path.dirname(output_path)
    
    try:
        # 为每个段落生成音频
        for i, segment in enumerate(segments):
            print(f"\n{'='*60}")
            print(f"正在处理第 {i+1}/{len(segments)} 个段落...")
            print(f"{'='*60}")
            
            try:
                # 生成配音脚本（启用流式输出以查看进度）
                voice_script = generate_voice_script(segment, stream=True)
                
                # 生成段落音频文件路径，直接保存在AUDIO_FOLDER中
                segment_audio_path = os.path.join(output_dir, f"{output_basename}_segment_{i}.mp3")
                
                # 使用EasyVoiceClient生成音频
                print(f"\n正在调用EasyVoice生成音频...")
                ev_client = EasyVoiceClient()
                ev_client.generate_audio(voice_script, segment_audio_path)
                
                # 只有成功生成的文件才添加到列表
                if os.path.exists(segment_audio_path):
                    segment_files.append(segment_audio_path)
                    print(f"第 {i+1} 个段落音频生成完成\n")
                else:
                    print(f"警告: 第 {i+1} 个段落音频文件未生成")
            except Exception as e:
                print(f"错误: 第 {i+1} 个段落处理失败: {str(e)}")
                import traceback
                traceback.print_exc()
                # 继续处理下一个段落
        
        # 连接所有段落音频文件
        if not segment_files:
            raise Exception("没有成功生成任何音频段落，无法合并")
        
        print(f"\n{'='*60}")
        print(f"正在合并 {len(segment_files)} 个音频文件...")
        _concatenate_audio_files(segment_files, output_path)
        print("所有音频合并完成！")
        print(f"{'='*60}\n")
        
    finally:
        # 清理段落文件（可选：如果希望保留段落文件用于调试，可以注释掉这部分）
        print("\n清理段落音频文件...")
        for segment_file in segment_files:
            if os.path.exists(segment_file):
                try:
                    os.remove(segment_file)
                    print(f"已删除: {os.path.basename(segment_file)}")
                except Exception as e:
                    print(f"删除失败 {os.path.basename(segment_file)}: {e}")
        print("清理完成\n")

def _concatenate_audio_files(audio_files, output_path):
    """
    连接多个音频文件
    
    Args:
        audio_files (list): 音频文件路径列表
        output_path (str): 输出文件路径
    """
    # 对于MP3文件，我们可以简单地连接它们的二进制内容
    with open(output_path, 'wb') as output_file:
        for audio_file in audio_files:
            with open(audio_file, 'rb') as f:
                shutil.copyfileobj(f, output_file)

def stream_chapter(app, chapter_id):
    chapter = Chapter.query.get_or_404(chapter_id)
    
    # Check if audio file already exists
    if chapter.audio_file_path and os.path.exists(chapter.audio_file_path):
        def generate():
            with open(chapter.audio_file_path, 'rb') as audio_file:
                while chunk := audio_file.read(4096):
                    yield chunk
        
        return Response(generate(), mimetype='audio/mpeg')
    
    # Get the novel associated with this chapter
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    # Get chapter content using the improved method
    try:
        chapter_data = get_chapter_content(novel.id, chapter_id)
        chapter_content = chapter_data['content'] if chapter_data else ""
    except Exception as e:
        print(f"获取章节内容时发生错误: {str(e)}")
        chapter_content = ""
    
    # Split content into segments of approximately 1500 characters
    # Each segment should end at a natural paragraph break
    segments = _split_content_into_segments(chapter_content, max_length=1500)
    
    # Generate audio file using easyvoice with voice script
    audio_filename = f"chapter_{chapter_id}.mp3"
    audio_path = os.path.join(app.config['AUDIO_FOLDER'], audio_filename)
    
    # Generate audio for each segment and concatenate
    _generate_audio_for_segments(segments, audio_path)
    
    # Update chapter record with audio file path
    chapter.audio_file_path = audio_path
    db.session.commit()
    
    # Stream the generated audio file
    def generate():
        with open(audio_path, 'rb') as audio_file:
            while chunk := audio_file.read(4096):
                yield chunk
    
    return Response(generate(), mimetype='audio/mpeg')