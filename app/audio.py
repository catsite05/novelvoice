import os
import tempfile
import shutil
import threading
import queue
import time
import json
from flask import send_file, Response, request
from models import Novel, Chapter, db
from chapter import get_chapter_content
from voice_script import generate_voice_script
from easyvoice_client import EasyVoiceClient


def preprocess_chapter_script(chapter_id):
    """
    为指定章节的第一个分段生成配音脚本并保存
    """
    # 获取章节内容
    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    try:
        chapter_data = get_chapter_content(novel.id, chapter_id)
        chapter_content = chapter_data['content'] if chapter_data else ""
    except Exception as e:
        print(f"获取章节内容时发生错误: {str(e)}")
        return False
    
    # 分段策略：只处理第一个分段
    segments = _split_content_into_segments(chapter_content, max_length=1500)
    if not segments:
        print("章节内容为空，无法生成配音脚本")
        return False
    
    # 只处理第一个分段
    first_segment = segments[0]
    
    # 检查是否已有保存的脚本
    script_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio', 'script')
    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_0_script.json')
    
    # 如果已经有缓存的脚本，直接返回
    if os.path.exists(script_cache_path):
        print(f"[预处理] 使用已缓存的脚本: {script_cache_path}")
        return True
    
    try:
        # 生成配音脚本
        voice_script = generate_voice_script(first_segment, stream=False)
        
        # 确保脚本缓存目录存在
        if not os.path.exists(script_folder):
            os.makedirs(script_folder)
        
        # 保存脚本到文件
        with open(script_cache_path, 'w', encoding='utf-8') as f:
            json.dump(voice_script, f, ensure_ascii=False, indent=2)
        
        print(f"[预处理] 章节 {chapter_id} 的第一个分段配音脚本已缓存到: {script_cache_path}")
        return True
        
    except Exception as e:
        print(f"[预处理] 生成章节 {chapter_id} 的配音脚本时发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def is_chapter_script_ready(chapter_id):
    """
    检查指定章节的第一个分段配音脚本是否已生成
    """
    script_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio', 'script')
    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_0_script.json')
    return os.path.exists(script_cache_path)

class GenerationManager:
    """管理章节音频生成任务,用于限制同时生成的章节数(最多1个)。"""
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks = {}  # chapter_id -> {'cancel_event': threading.Event()}

    def register_task(self, chapter_id, cancel_event):
        """注册新的生成任务,并取消其他章节的生成任务。"""
        with self._lock:
            # 取消其他章节的生成
            for cid, ctx in list(self._tasks.items()):
                if cid != chapter_id:
                    ev = ctx.get('cancel_event')
                    if ev and not ev.is_set():
                        print(f"[生成管理] 取消章节 {cid} 的生成任务")
                        ev.set()
                    del self._tasks[cid]
            # 记录当前章节任务
            self._tasks[chapter_id] = {'cancel_event': cancel_event}

    def cancel_task(self, chapter_id):
        """显式取消指定章节的生成任务(例如用户点击“停止播放”时调用)。"""
        with self._lock:
            ctx = self._tasks.get(chapter_id)
            if not ctx:
                return False
            ev = ctx.get('cancel_event')
            if ev and not ev.is_set():
                print(f"[生成管理] 显式取消章节 {chapter_id} 的生成任务")
                ev.set()
            return True

    def clear_task(self, chapter_id):
        """在任务正常完成或失败后,从管理器中移除。"""
        with self._lock:
            self._tasks.pop(chapter_id, None)


_generation_manager = GenerationManager()


def cancel_chapter_generation(chapter_id):
    """显式取消指定章节的后台生成任务。"""
    return _generation_manager.cancel_task(chapter_id)


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
                # 生成配音脚本（如需调试可启用流式输出以查看进度）
                voice_script = generate_voice_script(segment, stream=False)
                
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
    """
    真正的流式播放：边生成边传输，支持页面切换后继续生成
    三线程架构：脚本生成 + 音频生成 + 文件写入（独立）
    """
    chapter = Chapter.query.get_or_404(chapter_id)
        
    audio_path = os.path.join(app.config['AUDIO_FOLDER'], f'chapter_{chapter_id}.mp3')
    
    # 情况1: 文件已完整生成
    if chapter.audio_status == 'complete' and os.path.exists(audio_path):
        print(f"[缓存] 使用已完成的音频文件: {audio_path}")
        return send_file(audio_path, mimetype='audio/mpeg')
    
    # 情况2: 文件正在生成中(后台线程在工作)
    if chapter.audio_status == 'generating' and os.path.exists(audio_path):
        print(f"[恢复播放] 文件正在后台生成,流式返回现有内容: {audio_path}")
            
        def stream_existing_file():
            """流式读取正在增长的文件"""
            position = 0
            no_growth_count = 0
            last_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0
            
            while True:
                # 每次循环都重新打开文件,避免缓存问题
                try:
                    with open(audio_path, 'rb') as f:
                        
                        while True:
                            f.seek(position)
                            chunk = f.read(8192)
                        
                            if chunk:
                                yield chunk
                                position += len(chunk)
                                no_growth_count = 0
                                continue  # 立即读取下一块
                            else:
                                break

                except FileNotFoundError:
                    print("[恢复播放] 文件不存在,停止读取")
                    break
                
                # 读到文件末尾,检查状态和文件大小
                with app.app_context():
                    ch = Chapter.query.get(chapter_id)
                    
                    if ch and ch.audio_status == 'complete':
                        # 文件已完成,读取剩余数据后退出
                        print("[恢复播放] 文件生成完成,读取剩余数据")
                        try:
                            with open(audio_path, 'rb') as f:
                                f.seek(position)
                                remaining = f.read()
                                if remaining:
                                    yield remaining
                        except:
                            pass
                        break
                
                # 检查文件是否还在增长
                current_size = os.path.getsize(audio_path)
                if current_size > last_size:
                    # 文件增长了,继续读取
                    last_size = current_size
                    no_growth_count = 0
                    continue  # 不sleep,立即读取新数据
                elif current_size == last_size:
                    # 文件未增长
                    no_growth_count += 1
                    if no_growth_count > 60:  # 60秒未增长
                        print(f"[恢复播放] 文件长时间未增长,停止读取 (position={position}, size={current_size})")
                        break
                    # 等待新数据
                    time.sleep(1)
            
        
        return Response(stream_existing_file(), mimetype='audio/mpeg', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # 禁用nginx缓冲
        })
    
    # 情况3: 启动新的生成流程
    print(f"\n{'='*60}")
    print(f"开始生成章节 {chapter_id} 的音频")
    print(f"{'='*60}\n")
    
    # 清理可能存在的不完整文件
    if os.path.exists(audio_path):
        print(f"[清理] 删除旧的不完整文件: {audio_path}")
        os.remove(audio_path)
    
    # 标记状态为"生成中"
    chapter.audio_status = 'generating'
    db.session.commit()
    
    # 获取章节内容
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    try:
        chapter_data = get_chapter_content(novel.id, chapter_id)
        chapter_content = chapter_data['content'] if chapter_data else ""
    except Exception as e:
        print(f"获取章节内容时发生错误: {str(e)}")
        chapter.audio_status = 'failed'
        db.session.commit()
        return Response("Error loading content", status=500)
    
    # 分段策略：第一段极短（快速启动），后续段落正常长度
    segments = _split_content_into_segments(chapter_content, max_length=1500)
    
    # 共享队列和事件
    script_queue = queue.Queue(maxsize=5)  # 配音脚本队列
    audio_queue = queue.Queue(maxsize=10)  # 音频数据队列(增大防止阻塞)
    client_queue = queue.Queue(maxsize=10)  # 客户端队列
    complete_event = threading.Event()
    script_complete_event = threading.Event()
    cancel_event = threading.Event()  # 用于取消本章节的生成任务
    error_container = {'error': None}

    # 在生成管理器中注册本章节任务,并取消其他章节的生成
    _generation_manager.register_task(chapter_id, cancel_event)
    
    # 线程1：生成配音脚本（LLM调用）
    def script_producer():
        with app.app_context():
            try:
                for i, segment in enumerate(segments):
                    if cancel_event.is_set():
                        print(f"[脚本生成] 收到取消信号, 停止章节 {chapter_id} 的脚本生成")
                        error_container['error'] = error_container.get('error') or 'cancelled'
                        # 通知下游队列,让其他线程尽快退出
                        script_queue.put(('error', 'cancelled'))
                        return

                    print(f"\n[脚本生成] 正在处理第 {i+1}/{len(segments)} 段（{len(segment)} 字）...")
                    
                    # 检查是否已有保存的脚本
                    script_folder = os.path.join(app.config['AUDIO_FOLDER'], 'script')
                    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_{i}_script.json')
                    if os.path.exists(script_cache_path):
                        print(f"[脚本生成] 使用已缓存的脚本: {script_cache_path}")
                        with open(script_cache_path, 'r', encoding='utf-8') as f:
                            voice_script = json.load(f)
                    else:
                        # 生成配音脚本
                        voice_script = generate_voice_script(segment, stream=False)
                        # 确保脚本缓存目录存在
                        if not os.path.exists(script_folder):
                            os.makedirs(script_folder)
                        # 保存脚本到文件
                        with open(script_cache_path, 'w', encoding='utf-8') as f:
                            json.dump(voice_script, f, ensure_ascii=False, indent=2)
                        print(f"[脚本生成] 脚本已缓存到: {script_cache_path}")
                    
                    # 放入脚本队列，供音频生成线程使用
                    script_queue.put((i, voice_script))
                    print(f"[脚本生成] 第 {i+1} 段脚本已入队")
                
                # 脚本生成完成标记
                script_queue.put(('done', None))
                script_complete_event.set()
                print("\n[脚本生成] 所有脚本生成完成\n")
                
            except Exception as e:
                print(f"\n[脚本生成] 发生错误: {e}")
                import traceback
                traceback.print_exc()
                error_container['error'] = str(e)
                script_queue.put(('error', str(e)))
    
    # 线程2：调用 EasyVoice 生成音频
    def audio_producer():
        try:
            while True:
                if cancel_event.is_set():
                    print(f"[音频生成] 收到取消信号, 停止章节 {chapter_id} 的音频生成")
                    msg = error_container.get('error') or 'cancelled'
                    audio_queue.put(('error', msg))
                    complete_event.set()
                    break

                try:
                    # 从脚本队列获取
                    item = script_queue.get(timeout=180)
                    
                    if isinstance(item[0], str):
                        if item[0] == 'error':
                            print(f"[音频生成] 收到错误信号: {item[1]}")
                            audio_queue.put(('error', item[1]))
                            break
                        elif item[0] == 'done':
                            print("[音频生成] 收到脚本完成信号")
                            break
                    else:
                        i, voice_script = item
                        print(f"\n[音频生成] 正在生成第 {i+1} 段音频...")
                        
                        # 使用 EasyVoice 流式生成音频
                        ev_client = EasyVoiceClient()
                        
                        try:
                            # 关键：调用流式生成方法
                            for chunk in ev_client.generate_audio_stream(voice_script):
                                # 立即将音频块放入队列
                                audio_queue.put(('data', chunk))
                            
                            print(f"[音频生成] 第 {i+1} 段生成并入队完成")
                            
                        except Exception as e:
                            print(f"[音频生成] 第 {i+1} 段生成失败: {e}")
                            import traceback
                            traceback.print_exc()
                            error_container['error'] = str(e)
                            continue
                
                except queue.Empty:
                    if script_complete_event.is_set():
                        print("[音频生成] 脚本队列已空且生成完成")
                        break
                    else:
                        print("[音频生成] 等待脚本生成...")
                        continue
            
            # 音频生成完成标记
            audio_queue.put(('done', None))
            complete_event.set()
            print("\n[音频生成] 所有音频生成完成\n")
            
        except Exception as e:
            print(f"\n[音频生成] 发生错误: {e}")
            import traceback
            traceback.print_exc()
            error_container['error'] = str(e)
            audio_queue.put(('error', str(e)))
    
    # 线程3：独立的文件写入线程（关键！不受HTTP连接影响）
    def file_writer():
        """
        独立的文件写入线程，即使客户端断开连接也继续工作
        """
        file_complete = False
        
        try:
            with app.app_context():
                print("\n[文件写入] 线程启动\n")
                
                with open(audio_path, 'wb') as f:
                    while True:
                        if cancel_event.is_set():
                            print(f"[文件写入] 收到取消信号, 停止章节 {chapter_id} 的写入")
                            if not error_container['error']:
                                error_container['error'] = 'cancelled'
                            break
                        try:
                            msg_type, data = audio_queue.get(timeout=180)
                            
                            if msg_type == 'data':
                                # 写入文件
                                f.write(data)
                                f.flush()
                                
                                # 同时放入客户端队列（如果客户端在线）
                                try:
                                    client_queue.put(('data', data), block=False)
                                except queue.Full:
                                    # 客户端队列满了，说明客户端已断开或消费慢，忽略
                                    pass
                            
                            elif msg_type == 'done':
                                print("[文件写入] 音频生成完成")
                                file_complete = True
                                try:
                                    client_queue.put(('done', None), block=False)
                                except queue.Full:
                                    pass
                                break
                            
                            elif msg_type == 'error':
                                print(f"[文件写入] 收到错误: {data}")
                                error_container['error'] = data
                                try:
                                    client_queue.put(('error', data), block=False)
                                except queue.Full:
                                    pass
                                break
                        
                        except queue.Empty:
                            if complete_event.is_set():
                                file_complete = not error_container['error']
                                break
                
                # 更新数据库
                if file_complete and not error_container['error']:
                    ch = Chapter.query.get(chapter_id)
                    if ch:
                        ch.audio_file_path = audio_path
                        ch.audio_status = 'complete'
                        db.session.commit()
                        print(f"[文件写入] ✅ 文件完整生成并标记完成: {audio_path}\n")
                elif error_container['error']:
                    # 删除不完整文件
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                        print(f"[文件写入] ❌ 删除错误文件: {audio_path}")
                    
                    ch = Chapter.query.get(chapter_id)
                    if ch:
                        ch.audio_status = 'failed'
                        db.session.commit()
                
                # 通知生成管理器任务结束
                try:
                    _generation_manager.clear_task(chapter_id)
                except Exception as e:
                    print(f"[生成管理] 清理任务失败: {e}")
        
        except Exception as e:
            print(f"[文件写入] 异常: {e}")
            import traceback
            traceback.print_exc()
            
            # 标记失败
            try:
                with app.app_context():
                    ch = Chapter.query.get(chapter_id)
                    if ch:
                        ch.audio_status = 'failed'
                        db.session.commit()
            except:
                pass

            # 通知生成管理器任务结束
            try:
                _generation_manager.clear_task(chapter_id)
            except Exception as e2:
                print(f"[生成管理] 清理任务失败: {e2}")
    
    # 启动3个后台线程
    script_thread = threading.Thread(target=script_producer, daemon=True)
    audio_thread = threading.Thread(target=audio_producer, daemon=True)
    file_thread = threading.Thread(target=file_writer, daemon=True)  # 新增：独立文件写入线程
    
    script_thread.start()
    audio_thread.start()
    file_thread.start()
    
    # 消费者生成器：只负责转发数据给客户端
    def generate():
        try:
            print("\n[客户端] 开始流式传输音频数据...\n")
            
            timeout_seconds = 30
            first_data = True
            
            while True:
                try:
                    # 从客户端队列读取（不再从 audio_queue）
                    msg_type, data = client_queue.get(timeout=timeout_seconds)
                    
                    if msg_type == 'data':
                        yield data
                        
                        if first_data:
                            first_data = False
                            timeout_seconds = 180
                            print("[客户端] 第一段数据已发送，后续超时调整为180秒")
                    
                    elif msg_type == 'done':
                        print("[客户端] 传输完成")
                        break
                    
                    elif msg_type == 'error':
                        print(f"[客户端] 收到错误: {data}")
                        break
                
                except queue.Empty:
                    if complete_event.is_set():
                        print("[客户端] 生产者已结束，停止传输")
                        break
                    else:
                        print("[客户端] 队列空但生产者还在运行，继续等待...")
                        continue
        
        except GeneratorExit:
            print("[客户端] 连接断开（但文件写入继续！）")
        
        except Exception as e:
            print(f"[客户端] 异常: {e}")
            import traceback
            traceback.print_exc()
    
    return Response(
        generate(),
        mimetype='audio/mpeg',
        headers={
            'Cache-Control': 'no-cache',
            'X-Content-Type-Options': 'nosniff',
            'Transfer-Encoding': 'chunked'
        }
    )