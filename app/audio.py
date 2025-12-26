import os
import time
from threading import Lock
from flask import send_file, Response, request
from models import Novel, Chapter
from flask import g, abort
from audio_generator import generate_chapter_audio

# 音频生成已迁移到 audio_generator.py

# 全局播放流管理器
class PlaybackSessionManager:
    """
    管理每个用户的播放会话状态
    - 每个用户最多维护一个播放会话
    - 记录会话ID和已发送字节数
    - 会话ID变化时重置计数器
    """
    def __init__(self):
        self._sessions = {}  # {user_id: {'session_id': str, 'bytes_sent': int}}
        self._lock = Lock()
    
    def update_session(self, user_id, session_id, bytes_sent):
        """更新或创建用户的播放会话"""
        with self._lock:
            if user_id not in self._sessions:
                # 新用户会话
                self._sessions[user_id] = {
                    'session_id': session_id,
                    'bytes_sent': bytes_sent
                }
                print(f"[播放管理器] 创建新会话 user_id={user_id}, session_id={session_id}, bytes_sent={bytes_sent}")
            else:
                current_session = self._sessions[user_id]
                if current_session['session_id'] != session_id:
                    # 会话ID变化，重置计数器
                    print(f"[播放管理器] 会话ID变化 user_id={user_id}, old_session={current_session['session_id']}, new_session={session_id}，重置字节计数")
                    self._sessions[user_id] = {
                        'session_id': session_id,
                        'bytes_sent': bytes_sent
                    }
                else:
                    # 累加已发送字节数
                    self._sessions[user_id]['bytes_sent'] += bytes_sent
                    # print(f"[播放管理器] 累加字节数 user_id={user_id}, session_id={session_id}, total_bytes={self._sessions[user_id]['bytes_sent']}")
    
    def get_session(self, user_id):
        """获取用户的播放会话信息"""
        with self._lock:
            return self._sessions.get(user_id)
    
    def clear_session(self, user_id):
        """清除用户的播放会话"""
        with self._lock:
            if user_id in self._sessions:
                print(f"[播放管理器] 清除会话 user_id={user_id}")
                del self._sessions[user_id]

# 全局实例
playback_manager = PlaybackSessionManager()

def stream_chapter(app, chapter_id):
    """
    真正的流式播放：边生成边传输，支持页面切换后继续生成
    三线程架构：脚本生成 + 音频生成 + 文件写入（独立）
    """
    
    print(f"启动播放章节: {chapter_id}")

    # 打印请求头部信息
    # print(f"请求头部信息: {request.headers}")

    # 获取播放会话ID（必须在请求上下文中获取）
    playback_session_id = request.headers.get('X-Playback-Session-Id')
    if playback_session_id:
        print(f"播放会话ID: {playback_session_id}")

    # 打印Range头部参数
    range_header = request.headers.get('Range', None)
    start_pos = 0
    end_pos = None
    if range_header:
        print(f"Range头部参数: {range_header}")
        # 解析Range头部 (格式如: bytes=0-1023)
        if range_header.startswith('bytes='):
            range_value = range_header[6:]  # 移除 'bytes=' 前缀
            if '-' in range_value:
                start_str, end_str = range_value.split('-', 1)
                start_pos = int(start_str) if start_str else 0
                end_pos = int(end_str) if end_str else None

    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)

    # 权限校验
    user = getattr(g, 'current_user', None)
    if user is None:
        abort(401)
    if not user.is_superuser and novel.user_id != user.id:
        abort(403)
    
    # 捕获用户ID供后续线程使用
    user_id = user.id

    audio_path = os.path.join(app.config['AUDIO_FOLDER'], f'chapter_{chapter_id}.mp3')
    
    # 情况1: 文件已完整生成，且未开始分段播放
    if chapter.audio_status == 'complete' and os.path.exists(audio_path):
        bytes_sent = 0
        if playback_session_id:
            # 获取session中保存的bytes_sent
            session = playback_manager.get_session(user_id)
            bytes_sent = session['bytes_sent'] if session and session['session_id'] == playback_session_id else 0
            print(f"[播放] 获取会话进度 bytes_sent={bytes_sent}")

        # 如果分段播放已经开始，则需要继续使用分段播放
        # if bytes_sent == 0:
        #     print(f"[缓存] 使用已完成的音频文件: {audio_path}")
        #     return send_file(audio_path, mimetype='audio/mpeg')
    
    def stream_existing_file(start_pos=0, session_id=None):
        """流式读取正在增长的文件，支持客户端断开连接时优雅退出"""
        
        position = start_pos
        if position == 0 and session_id:
            # 获取session中保存的bytes_sent
            session = playback_manager.get_session(user_id)
            position = session['bytes_sent'] if session and session['session_id'] == session_id else 0
            print(f"[播放] 获取会话进度 position={position}")

        no_growth_count = 0
        last_size = 0
        client_disconnected = False

        try:
            last_size = os.path.getsize(audio_path)
        except:
            print("[播放] 文件尚未存在，等待文件生成")
        
        try:
            while not client_disconnected:
                # 每次循环都重新打开文件,避免缓存问题
                try:
                    with open(audio_path, 'rb') as f:                   
                        while True:
                            f.seek(position)
                            chunk = f.read(8192)                        
                            if chunk:
                                try:
                                    yield chunk
                                    chunk_size = len(chunk)
                                    position += chunk_size
                                    no_growth_count = 0
                                    
                                    # 如果有会话ID，更新播放管理器
                                    if session_id:
                                        playback_manager.update_session(user_id, session_id, chunk_size)
                                except GeneratorExit:
                                    # 客户端断开连接
                                    print("[播放] 服务器断开连接 -- 1")
                                    client_disconnected = True
                                    # 打印会话进度
                                    if session_id:
                                        session = playback_manager.get_session(user_id)
                                        print(f"[播放] 已保存进度 position={session['bytes_sent']}")
                                    return
                            else:
                                break
                except GeneratorExit:
                    print("[播放] 服务器断开连接 -- 2")
                    client_disconnected = True
                    return
                except Exception:
                    print("[播放] 文件尚未存在，等待文件生成")
                    
                # 检查文件是否还在增长
                current_size = last_size
                no_growth_count = 0
                while current_size <= last_size:
                    time.sleep(1)
                    no_growth_count += 1
                    # 文件未增长超时
                    if no_growth_count > 60:
                        print(f"[播放] 文件长时间未增长,停止读取 (position={position}, size={current_size})")
                        return
                    # 等待新数据
                    try:
                        current_size = os.path.getsize(audio_path)
                    except:
                        print("[播放] 文件已被删除，停止流式传输")
                        return

                if current_size <= last_size:
                    return
                else:
                    last_size = current_size
                    
        except GeneratorExit:
            # 客户端断开连接时静默退出（页面切换时的正常行为）
            print("[播放] 服务器断开连接 -- 3")
            pass
        except Exception as e:
            print(f"[播放] 流式传输发生错误: {e}")
                          
    # iPhone的Safari浏览器会先请求前两个字节，在这里做特殊处理：发送状态码是206的响应消息，消息的数据部分是两个字节0xff和0xf3
    if start_pos == 0 and end_pos == 1:
        response_data = b"\xff\xf3"
        return Response(
                response_data,
                status=206,
                mimetype="audio/mpeg",
                headers={
                    "Content-Range": f"bytes 0-1/*",
                    "Accept-Ranges": "bytes",
                    "Content-Length": "2"
                }
            )                

    # 情况2: 文件正在生成中(后台线程在工作)，或者文件已生成但已开始分段播放
    if os.path.exists(audio_path):
        print(f"[播放] 文件正在后台生成,流式返回现有内容: {audio_path}")
                    
        return Response(
            stream_existing_file(start_pos, playback_session_id), 
            mimetype='audio/mpeg', 
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',  # 禁用nginx缓冲
            }
        )
    
    # 情况3: 启动新的生成流程
    print(f"\n{'='*60}")
    print(f"开始生成章节 {chapter_id} 的音频")
    print(f"{'='*60}\n")
    
    # 启动音频生成（使用audio_generator模块）
    try:
        generate_chapter_audio(app, chapter_id, user_id, audio_path)
    except:
        return Response("Error loading content", status=500)
    
    return Response(
            stream_existing_file(start_pos, playback_session_id), 
            mimetype='audio/mpeg', 
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',  # 禁用nginx缓冲
            }
        )