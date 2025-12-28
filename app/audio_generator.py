"""
音频生成模块
负责配音脚本生成、音频合成、内容分段和生成任务管理
"""
import os
import threading
import queue
import json
import time
from models import Novel, Chapter, db
from flask import g, abort
from chapter import _read_chapter_content
from voice_script import generate_voice_script
from easyvoice_client import EasyVoiceClient
from edgetts_client import EdgeTTSClient


# ===== 断点续传相关函数 =====

def _get_resume_file_path(audio_path):
    """获取断点文件路径"""
    return audio_path.replace('.mp3', '.resume.json')


def _load_resume_point(audio_path):
    """
    加载断点信息

    Returns:
        dict or None: 断点信息，包含：
            - segment_index: 最后完成的segment索引
            - last_completed_item: 该segment中最后完成的item索引
            - audio_file_size: 当前音频文件大小
    """
    resume_file = _get_resume_file_path(audio_path)
    if not os.path.exists(resume_file):
        return None

    try:
        with open(resume_file, 'r', encoding='utf-8') as f:
            resume_data = json.load(f)

        # 验证音频文件是否存在（暂不验证大小匹配）
        if os.path.exists(audio_path):
            # actual_size = os.path.getsize(audio_path)
            # expected_size = resume_data.get('audio_file_size', 0)

            # if actual_size == expected_size:
            #     print(f"[断点续传] 找到有效断点: segment={resume_data.get('segment_index')}, "
            #           f"item={resume_data.get('last_completed_item')}, size={actual_size}")
            #     return resume_data
            # else:
            #     print(f"[断点续传] 音频文件大小不匹配 (实际: {actual_size}, 预期: {expected_size})，忽略断点")
            #     return None
            return resume_data
        else:
            print(f"[断点续传] 音频文件不存在，忽略断点")
            return None

    except Exception as e:
        print(f"[断点续传] 加载断点文件失败: {e}")
        return None


def _save_resume_point(audio_path, chapter_id, segment_index, last_completed_item):
    """
    保存断点信息

    Args:
        audio_path: 音频文件路径
        chapter_id: 章节ID
        segment_index: 当前segment索引
        last_completed_item: 该segment中最后完成的item索引
    """
    try:
        resume_file = _get_resume_file_path(audio_path)
        audio_file_size = os.path.getsize(audio_path) if os.path.exists(audio_path) else 0

        resume_data = {
            'chapter_id': chapter_id,
            'segment_index': segment_index,
            'last_completed_item': last_completed_item,
            'audio_file_size': audio_file_size,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }

        with open(resume_file, 'w', encoding='utf-8') as f:
            json.dump(resume_data, f, ensure_ascii=False, indent=2)

        # print(f"[断点续传] 保存断点: segment={segment_index}, item={last_completed_item}, size={audio_file_size}")

    except Exception as e:
        print(f"[断点续传] 保存断点文件失败: {e}")


def _delete_resume_file(audio_path):
    """删除断点文件"""
    try:
        resume_file = _get_resume_file_path(audio_path)
        if os.path.exists(resume_file):
            os.remove(resume_file)
            print(f"[断点续传] 删除断点文件: {resume_file}")
    except Exception as e:
        print(f"[断点续传] 删除断点文件失败: {e}")


# ===== 原有代码 =====

class GenerationManager:
    """管理章节音频生成任务,支持多用户并发(每个用户最多同时生成1个章节)。"""
    def __init__(self):
        self._lock = threading.Lock()
        self._tasks = {}  # user_id -> {'chapter_id': int, 'cancel_event': threading.Event()}

    def register_task(self, user_id, chapter_id, cancel_event):
        """注册新的生成任务,并取消该用户的其他章节生成任务。
        
        Args:
            user_id: 用户ID
            chapter_id: 章节ID
            cancel_event: 取消事件对象
        """
        with self._lock:
            # 取消该用户其他章节的生成
            if user_id in self._tasks:
                old_task = self._tasks[user_id]
                old_chapter_id = old_task.get('chapter_id')
                old_cancel_event = old_task.get('cancel_event')
                
                if old_chapter_id != chapter_id and old_cancel_event and not old_cancel_event.is_set():
                    print(f"[生成管理] 用户 {user_id} 取消章节 {old_chapter_id} 的生成任务")
                    old_cancel_event.set()
            
            # 记录当前用户的新任务
            self._tasks[user_id] = {
                'chapter_id': chapter_id,
                'cancel_event': cancel_event
            }
            print(f"[生成管理] 用户 {user_id} 注册章节 {chapter_id} 的生成任务")

    def cancel_task(self, user_id, chapter_id):
        """显式取消指定用户的指定章节生成任务。
        
        Args:
            user_id: 用户ID
            chapter_id: 章节ID
        
        Returns:
            bool: 是否成功取消
        """
        with self._lock:
            task = self._tasks.get(user_id)
            if not task or task.get('chapter_id') != chapter_id:
                return False
            
            cancel_event = task.get('cancel_event')
            if cancel_event and not cancel_event.is_set():
                print(f"[生成管理] 用户 {user_id} 显式取消章节 {chapter_id} 的生成任务")
                cancel_event.set()
            return True

    def clear_task(self, user_id, chapter_id):
        """在任务正常完成或失败后,从管理器中移除。
        
        Args:
            user_id: 用户ID
            chapter_id: 章节ID
        """
        with self._lock:
            task = self._tasks.get(user_id)
            if task and task.get('chapter_id') == chapter_id:
                self._tasks.pop(user_id, None)
                print(f"[生成管理] 用户 {user_id} 清理章节 {chapter_id} 的任务记录")


# 全局生成管理器实例
_generation_manager = GenerationManager()

# 检查本用户是否正在生成章节音频
def check_chapter_generating(user_id, chapter_id):
    """检查本用户是否正在生成指定章节的音频。
    
    Args:
        user_id: 用户ID
        chapter_id: 章节ID
    
    Returns:
        bool: 是否正在生成
    """
    task = _generation_manager._tasks.get(user_id)
    return task and task.get('chapter_id') == chapter_id

def cancel_chapter_generation(user_id, chapter_id):
    """显式取消指定用户的指定章节后台生成任务。
    
    Args:
        user_id: 用户ID
        chapter_id: 章节ID
    
    Returns:
        bool: 是否成功取消
    """
    return _generation_manager.cancel_task(user_id, chapter_id)


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


def preprocess_chapter_script(chapter_id):
    """
    为指定章节的第一个分段生成配音脚本并保存
    """
    # 获取章节内容
    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)

    # 仅在有请求上下文时做权限校验（后台预处理线程不检查 g.current_user）
    try:
        user = g.current_user
    except Exception:
        user = None
    if user is not None and (not user.is_superuser and novel.user_id != user.id):
        abort(403)
    
    try:
        # 直接从文件中读取章节内容，避免通过 HTTP 层的权限校验
        all_chapters = Chapter.query.filter_by(novel_id=novel.id).order_by(Chapter.start_position).all()
        current_index = next((i for i, ch in enumerate(all_chapters) if ch.id == chapter_id), -1)
        if current_index == -1:
            print(f"章节 {chapter_id} 不存在于小说 {novel.id} 中")
            return False

        if current_index < len(all_chapters) - 1:
            end_position = all_chapters[current_index + 1].start_position
        else:
            end_position = None

        chapter_content = _read_chapter_content(novel.file_path, chapter.start_position, end_position)
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
    script_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio', 'script', f'novel-{novel.id}')
    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_0_script.json')
    
    # 如果已经有缓存的脚本，直接返回
    if os.path.exists(script_cache_path):
        print(f"[预处理] 使用已缓存的脚本: {script_cache_path}")
        return True
    
    try:
        # 获取小说专有的LLM配置
        llm_api_key = novel.llm_api_key if novel.llm_api_key else None
        llm_base_url = novel.llm_base_url if novel.llm_base_url else None
        llm_model = novel.llm_model if novel.llm_model else None
        
        # 生成配音脚本，传入小说专有的LLM配置
        voice_script = generate_voice_script(first_segment, stream=False, 
                                            llm_api_key=llm_api_key,
                                            llm_base_url=llm_base_url,
                                            llm_model=llm_model)
        
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
    # 查询章节和小说信息
    chapter = Chapter.query.get(chapter_id)
    if not chapter:
        return False

    novel = Novel.query.get(chapter.novel_id)
    if not novel:
        return False

    # 权限校验：仅在有请求上下文时检查
    try:
        user = g.current_user
        if user is not None:
            if not user.is_superuser and novel.user_id != user.id:
                abort(403)
    except Exception:
        # 没有请求上下文（如在后台线程中），跳过权限检查
        pass

    script_folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'audio', 'script', f'novel-{novel.id}')
    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_0_script.json')
    return os.path.exists(script_cache_path)


def check_and_preprocess_next_chapter(current_chapter_id):
    """
    检查当前章节的小说是否有下一章，如果有且下一章尚未预处理，则启动预处理
    """
    try:
        # 获取当前章节
        current_chapter = Chapter.query.get(current_chapter_id)
        if not current_chapter:
            print(f"[预处理检查] 未找到当前章节 {current_chapter_id}")
            return
        
        # 直接查询chapter_id大于本章的第一个章节（即下一章）
        next_chapter = Chapter.query.filter(
            Chapter.novel_id == current_chapter.novel_id,
            Chapter.start_position > current_chapter.start_position
        ).order_by(Chapter.start_position).first()
        
        # 如果存在下一章，则检查是否需要预处理
        if next_chapter:            
            # 检查下一章是否已经预处理过
            if not is_chapter_script_ready(next_chapter.id):
                print(f"[预处理检查] 章节 {current_chapter_id} 的下一章 {next_chapter.id} 尚未预处理，启动预处理...")                
                # 直接预处理下一章（已在后台线程中执行）
                preprocess_chapter_script(next_chapter.id)
            else:
                print(f"[预处理检查] 章节 {current_chapter_id} 的下一章 {next_chapter.id} 已经预处理完成")
        else:
            print(f"[预处理检查] 章节 {current_chapter_id} 是小说的最后一章，无需检查下一章")
            
    except Exception as e:
        print(f"[预处理检查] 检查下一章时发生错误: {e}")
        import traceback
        traceback.print_exc()


def generate_chapter_audio(app, chapter_id, user_id, audio_path):
    """
    生成章节音频的核心逻辑
    三线程架构:脚本生成 + 音频生成
    支持断点续传

    Args:
        app: Flask应用实例
        chapter_id: 章节ID
        user_id: 用户ID
        audio_path: 音频文件路径

    Note:
        每个任务使用独立的队列和事件对象,避免多任务并发冲突
    """

    # 尝试加载断点
    resume_data = _load_resume_point(audio_path)
    start_segment = 0
    start_item = 0
    file_mode = 'wb'  # 默认覆盖写入

    if resume_data:
        start_segment = resume_data.get('segment_index', 0)
        start_item = resume_data.get('last_completed_item', -1) + 1  # 从下一个item开始
        file_mode = 'ab'  # 追加模式
        print(f"[断点续传] 从 segment={start_segment}, item={start_item} 继续生成")
    else:
        # 清理可能存在的不完整文件
        if os.path.exists(audio_path):
            print(f"[清理] 删除旧的不完整文件: {audio_path}")
            os.remove(audio_path)

    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)

    # 标记状态为"生成中"
    chapter.audio_status = 'generating'
    db.session.commit()

    try:
        # 直接从文件中读取章节内容
        all_chapters = Chapter.query.filter_by(novel_id=novel.id).order_by(Chapter.start_position).all()
        current_index = next((i for i, ch in enumerate(all_chapters) if ch.id == chapter_id), -1)
        if current_index == -1:
            print(f"章节 {chapter_id} 不存在于小说 {novel.id} 中")
            error_container['error'] = 'Chapter not found'
            return

        if current_index < len(all_chapters) - 1:
            end_position = all_chapters[current_index + 1].start_position
        else:
            end_position = None

        chapter_content = _read_chapter_content(novel.file_path, chapter.start_position, end_position)
    except Exception as e:
        print(f"获取章节内容时发生错误: {str(e)}")
        chapter.audio_status = 'failed'
        db.session.commit()
        error_container['error'] = str(e)
        # 抛出异常
        raise e

    # 分段策略：第一段极短（快速启动），后续段落正常长度
    segments = _split_content_into_segments(chapter_content, max_length=1500)

    # 为本次任务创建独立的队列和事件对象
    script_queue = queue.Queue(maxsize=10)  # 配音脚本队列
    complete_event = threading.Event()  # 音频生成完成事件
    script_complete_event = threading.Event()  # 脚本生成完成事件
    cancel_event = threading.Event()  # 取消事件
    error_container = {'error': None}  # 错误容器
    # cancel_event.clear()
    # complete_event.clear()
    # 在生成管理器中注册本章节任务,并取消该用户的其他章节生成
    _generation_manager.register_task(user_id, chapter_id, cancel_event)
    
    # 线程1：生成配音脚本（LLM调用）
    def script_producer():
        with app.app_context():
            try:
                # 获取小说专有的LLM配置
                llm_api_key = novel.llm_api_key if novel.llm_api_key else None
                llm_base_url = novel.llm_base_url if novel.llm_base_url else None
                llm_model = novel.llm_model if novel.llm_model else None

                for i, segment in enumerate(segments):
                    # 断点续传：跳过已完成的segments
                    if i < start_segment:
                        # print(f"[脚本生成] 跳过已完成的第 {i+1}/{len(segments)} 段")
                        continue

                    # print(f"\n[脚本生成] 正在处理第 {i+1}/{len(segments)} 段（{len(segment)} 字）...")

                    # 检查是否已有保存的脚本
                    script_folder = os.path.join(app.config['AUDIO_FOLDER'], 'script', f'novel-{novel.id}')
                    # 如果script_folder不存在则创建
                    os.makedirs(script_folder, exist_ok=True)
                    script_cache_path = os.path.join(script_folder, f'chapter_{chapter_id}_segment_{i}_script.json')
                    if os.path.exists(script_cache_path):
                        # print(f"[脚本生成] 使用已缓存的脚本: {script_cache_path}")
                        with open(script_cache_path, 'r', encoding='utf-8') as f:
                            voice_script = json.load(f)
                    else:
                        # 生成配音脚本，传入小说专有的LLM配置，支持最多3次重试
                        max_retries = 3
                        voice_script = None
                        last_error = None
                        
                        for retry in range(max_retries):  
                            try:
                                voice_script = generate_voice_script(segment, stream=False,
                                                                    llm_api_key=llm_api_key,
                                                                    llm_base_url=llm_base_url,
                                                                    llm_model=llm_model)
                                break  # 成功则跳出重试循环
                            except Exception as e:
                                last_error = e
                                if retry < max_retries - 1:
                                    print(f"[脚本生成] 第 {retry + 1} 次尝试失败: {str(e)}，准备重试...")
                                else:
                                    print(f"[脚本生成] 重试 {max_retries} 次后仍然失败: {str(e)}")
                        
                        # 如果所有重试都失败，跳过这个segment
                        if voice_script is None:
                            continue
                        
                        # 确保脚本缓存目录存在
                        if not os.path.exists(script_folder):
                            os.makedirs(script_folder)
                        # 保存脚本到文件
                        with open(script_cache_path, 'w', encoding='utf-8') as f:
                            json.dump(voice_script, f, ensure_ascii=False, indent=2)
                        # print(f"[脚本生成] 脚本已缓存到: {script_cache_path}")
                    
                    # 放入脚本队列，供音频生成线程使用
                    # 附加segment索引信息，用于断点续传
                    current_start_item = start_item if i == start_segment else 0
                    script_queue.put((i, voice_script, current_start_item))
                    # print(f"[脚本生成] 第 {i+1} 段脚本已入队")

                    if cancel_event.is_set():
                        print(f"[脚本生成] 收到取消信号, 停止章节 {chapter_id} 的脚本生成")
                        error_container['error'] = error_container.get('error') or 'cancelled'
                        # 通知下游队列,让其他线程尽快退出
                        script_queue.put(('error', 'cancelled', 0))
                        return

                # 脚本生成完成标记
                script_queue.put(('done', None, 0))
                print("\n[脚本生成] 所有脚本生成完成\n")

                # 检查并预处理下一章
                check_and_preprocess_next_chapter(chapter_id)
                script_complete_event.set()

            except Exception as e:
                print(f"\n[脚本生成] 发生错误: {e}")
                # import traceback
                # traceback.print_exc()
                error_container['error'] = str(e)
                script_queue.put(('error', str(e), 0))
    
    # 线程2：调用 EasyVoice/EdgeTTS 生成音频并写入文件
    def audio_producer():
        file_completed = False
        current_segment_index = start_segment  # 当前处理的segment索引

        try:
            # 打开音频文件进行写入（追加或覆盖）
            with open(audio_path, file_mode) as f:
                while True:
                    if cancel_event.is_set():
                        print(f"[音频生成] 收到取消信号, 停止章节 {chapter_id} 的音频生成")
                        complete_event.set()
                        break

                    try:
                        # 从脚本队列获取
                        item = script_queue.get(timeout=180)
                        # 处理错误
                        if item[0] == 'error':
                            print(f"[音频生成] 收到错误信号: {item[1]}")
                            break

                        # 处理完成信号
                        elif item[0] == 'done':
                            print("[音频生成] 收到脚本完成信号，所有音频生成完成")

                            # 更新数据库
                            try:
                                 with app.app_context():
                                    ch = db.session.get(Chapter, chapter_id)
                                    if ch and not error_container['error']:
                                        ch.audio_file_path = audio_path
                                        ch.audio_status = 'complete'
                                        db.session.commit()
                                        print(f"[音频生成] ✅ 文件完整生成并标记完成: {audio_path}\n")

                                        # 删除断点文件
                                        _delete_resume_file(audio_path)
                                    else:
                                        print(f"[音频生成] 文件生成完成但遇到错误，略过标记: {error_container['error']}")
                            except Exception as e:
                                print(f"[音频生成] 更新数据库失败: {e}")
                                import traceback
                                traceback.print_exc()

                            complete_event.set()
                            file_completed = True

                            # 通知生成管理器任务结束
                            try:
                                _generation_manager.clear_task(user_id, chapter_id)
                            except Exception as e:
                                 print(f"[生成管理] 清理任务失败: {e}")
                            break

                        # 处理脚本
                        else:
                            segment_index, voice_script, segment_start_item = item
                            current_segment_index = segment_index
                            # print(f"\n[音频生成] 正在生成第 {segment_index+1} 段音频...")

                            # 创建进度回调函数，保存断点
                            def progress_callback(item_index):
                                _save_resume_point(audio_path, chapter_id, current_segment_index, item_index)

                            # 使用 EdgeTTS 流式生成音频（默认）
                            # 如果需要使用 EasyVoice，设置环境变量 USE_EASYVOICE=1
                            use_easyvoice = os.getenv('USE_EASYVOICE', '0') == '1'

                            if use_easyvoice:
                                print(f"[音频生成] 使用 EasyVoice 生成第 {segment_index+1} 段")
                                client = EasyVoiceClient()
                            else:
                                # print(f"[音频生成] 使用 EdgeTTS 生成第 {segment_index+1} 段")
                                client = EdgeTTSClient()

                            try:
                                # 关键:调用流式生成方法,传入cancel_event和断点续传参数
                                # 使用100K缓存
                                BUFFER_SIZE = 100 * 1024  # 100KB
                                buffer = bytearray()

                                if use_easyvoice:
                                    # EasyVoice不支持cancel_event参数
                                    for chunk in client.generate_audio_stream(
                                        voice_script,
                                        start_item=segment_start_item,
                                        progress_callback=progress_callback
                                    ):
                                        buffer.extend(chunk)

                                        # 当缓存达到100K时写入文件
                                        if len(buffer) >= BUFFER_SIZE:
                                            f.write(buffer)
                                            f.flush()
                                            buffer.clear()

                                        if cancel_event.is_set():
                                            break

                                    # 写入剩余缓存
                                    if buffer:
                                        f.write(buffer)
                                        f.flush()
                                else:
                                    # EdgeTTS支持cancel_event参数
                                    for chunk in client.generate_audio_stream(
                                        voice_script,
                                        cancel_event=cancel_event,
                                        start_item=segment_start_item,
                                        progress_callback=progress_callback
                                    ):
                                        buffer.extend(chunk)

                                        # 当缓存达到100K时写入文件
                                        if len(buffer) >= BUFFER_SIZE:
                                            f.write(buffer)
                                            f.flush()
                                            buffer.clear()

                                    # 写入剩余缓存
                                    if buffer:
                                        f.write(buffer)
                                        f.flush()

                                # print(f"[音频生成] 第 {segment_index+1} 段生成并写入完成")

                            except Exception as e:
                                print(f"[音频生成] 第 {segment_index+1} 段生成失败: {e}")
                                import traceback
                                traceback.print_exc()
                                error_container['error'] = str(e)
                                continue # ！！一般是脚本有错误，目前只是简单地先跳过这一段

                    except queue.Empty:
                        if script_complete_event.is_set():
                            print("[音频生成] 脚本队列已空且生成完成")
                            break
                        else:
                            print("[音频生成] 等待脚本生成...")
                            continue

        except Exception as e:
            print(f"\n[音频生成] 发生错误: {e}")
            import traceback
            traceback.print_exc()
            error_container['error'] = str(e)

        # 通知生成管理器任务结束
        try:
            _generation_manager.clear_task(user_id, chapter_id)
        except Exception as e2:
            print(f"[生成管理] 清理任务失败: {e2}")

        # 如果文件未完成，保留断点文件（不删除音频文件）
        if not file_completed:
            print(f"[音频生成] ⚠️  音频生成未完成，断点已保存: {_get_resume_file_path(audio_path)}")

            # 标记失败
            try:
                with app.app_context():
                    ch = db.session.get(Chapter, chapter_id)
                    if ch:
                        ch.audio_status = 'failed'
                        db.session.commit()
            except:
                pass
    
    # 启动2个后台线程
    script_thread = threading.Thread(target=script_producer, daemon=True)
    audio_thread = threading.Thread(target=audio_producer, daemon=True)
    
    script_thread.start()
    audio_thread.start()
