"""
HLS管理器 - 基于FFmpeg原生HLS功能
负责将MP3音频转换为HLS格式,支持混合方案(已生成/正在生成)
"""
import os
import subprocess
import threading
from threading import Lock
from flask import g, abort, send_file, send_from_directory
import time
from audio_generator import check_chapter_generating, generate_chapter_audio
from models import Chapter, Novel

class HLSManager:
    """HLS转换和管理器"""
    
    def __init__(self, hls_base_dir='hls_cache'):
        """
        初始化HLS管理器
            
        Args:
            hls_base_dir: HLS缓存根目录
        """
        # 确保使用绝对路径
        self.hls_base_dir = os.path.abspath(hls_base_dir)
        self._conversion_locks = {}  # chapter_id -> Lock (防止重复转换)
        self._global_lock = Lock()
            
        # 确保hls缓存目录存在
        if not os.path.exists(self.hls_base_dir):
            os.makedirs(self.hls_base_dir)
            print(f"[HLS管理器] 创建HLS缓存目录: {self.hls_base_dir}")
    
    def get_hls_dir(self, user_id):
        """获取章节的HLS目录路径"""
        return os.path.join(self.hls_base_dir, f'user_{user_id}')
    
    def get_playlist_path(self, user_id):
        """获取章节的playlist.m3u8路径"""
        return os.path.join(self.get_hls_dir(user_id), 'playlist.m3u8')
    
    def is_hls_exists(self, user_id):
        """检查HLS是否已经转换完成"""
        playlist_path = self.get_playlist_path(user_id)
        return os.path.exists(playlist_path)

    def is_hls_ready(self, user_id):
        """检查HLS是否已经转换完成"""
        playlist_path = self.get_playlist_path(user_id)
        if not os.path.exists(playlist_path):
            return False
        
        # 检查playlist.m3u8是否包含结束标记
        try:
            with open(playlist_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return '#EXT-X-ENDLIST' in content
        except:
            return False
    
    def _get_conversion_lock(self, user_id):
        """获取章节的转换锁"""
        with self._global_lock:
            if user_id not in self._conversion_locks:
                self._conversion_locks[user_id] = Lock()
            return self._conversion_locks[user_id]
    
    def _get_playlist_duration(self, playlist_path):
        """
        从 playlist.m3u8 读取已转换的总时长
        
        Args:
            playlist_path: playlist.m3u8 文件路径
        
        Returns:
            float: 已转换的总时长（秒）
        """
        if not os.path.exists(playlist_path):
            return 0.0
        
        try:
            total_duration = 0.0
            with open(playlist_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('#EXTINF:'):
                        # #EXTINF:6.000000,
                        duration_str = line.split(':')[1].split(',')[0]
                        total_duration += float(duration_str)
            
            return total_duration
        except Exception as e:
            print(f"[HLS管理器] 读取playlist时长失败: {e}")
            return 0.0
    
    def _count_segments(self, hls_dir):
        """
        统计已有的TS分段数量
        
        Returns:
            int: 已存在的分段数
        """
        import glob
        segments = glob.glob(os.path.join(hls_dir, 'segment_*.ts'))
        return len(segments)
    
    def _remove_endlist_if_exists(self, playlist_path):
        """
        移除 playlist.m3u8 中的 #EXT-X-ENDLIST 标记
        用于支持边生成边播放
        
        Args:
            playlist_path: playlist.m3u8 文件路径
        """
        try:
            with open(playlist_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 检查是否包含ENDLIST
            if '#EXT-X-ENDLIST' in content:
                # 移除ENDLIST行
                lines = content.split('\n')
                lines = [line for line in lines if line.strip() != '#EXT-X-ENDLIST']
                content = '\n'.join(lines)
                
                with open(playlist_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # print(f"[HLS管理器] 已移除ENDLIST标记，支持边生成边播放")
        except Exception as e:
            print(f"[HLS管理器] 移除ENDLIST失败: {e}")
    
    def _build_base_ffmpeg_cmd(self, mp3_path, segment_pattern, playlist_path, start_time):
        """
        构建基础的 FFmpeg HLS 转换命令（首次转换）
        
        Args:
            mp3_path: MP3文件路径
            segment_pattern: 分段文件名模式
            playlist_path: playlist.m3u8路径
            playlist_type: 'event'(正在生成) 或 'vod'(已完成)
        
        Returns:
            list: FFmpeg命令参数列表
        """
        return [
            'ffmpeg',
            '-ss', str(start_time),             # 🔑 跳过已转换部分
            # '-t', '60',                            # 每次处理60秒
            '-i', mp3_path,
            '-c:a', 'aac',                     
            '-f', 'hls',                        # 输出格式HLS
            '-hls_time', '9999',                # 整个文件成一段
            '-hls_list_size', '0',              # 如果要保留所有分段设为0
            # '-hls_playlist_type', playlist_type, # event=无ENDLIST, vod=有ENDLIST
            '-hls_segment_type', 'mpegts',      # 使用MPEG-TS容器
            '-hls_flags', 'independent_segments+append_list', # 🔑 追加模式，自动计算编号
            '-hls_segment_filename', segment_pattern,
            # '-y',                               # 覆盖已存在的文件
            playlist_path
        ]
    
    def _build_incremental_ffmpeg_cmd(self, mp3_path, segment_pattern, playlist_path, start_time):
        """
        构建增量 FFmpeg HLS 转换命令（追加新分段）
        
        Args:
            mp3_path: MP3文件路径
            segment_pattern: 分段文件名模式
            playlist_path: playlist.m3u8路径
            start_time: 起始时间（秒）
            start_segment: 起始分段编号（备注：不使用，保留参数以保持接口一致）
        
        Returns:
            list: FFmpeg命令参数列表
        """
        # 使用 append_list 时，FFmpeg 会自动从 playlist 读取已有分段编号

        # 用iPhone safari浏览器访问时，第一次必须生成多个分段，否则会重复下载第一个分段，不知道是什么原因
        duration = 60 if start_time > 0 else 12
        slice = 60 if start_time > 0 else 6
        return [
            'ffmpeg',
            '-ss', str(start_time),             # 🔑 跳过已转换部分
            '-t', str(duration),
            '-i', mp3_path,
            '-c:a', 'aac',
            '-f', 'hls',
            '-hls_time', str(slice),
            '-hls_list_size', '0',
            # '-hls_playlist_type', 'live',      # live模式（无ENDLIST）
            '-hls_segment_type', 'mpegts',
            '-hls_flags', 'independent_segments+append_list',  # 🔑 追加模式，自动计算编号
            '-hls_segment_filename', segment_pattern,
            playlist_path
        ]
    
    def convert_mp3_to_hls(self, mp3_path, timestamp, is_generating=False):
        """
        将MP3转换为HLS格式（支持增量转换）
        
        Args:
            chapter_id: 章节ID
            mp3_path: MP3文件路径
            force: 是否强制重新转换
            is_generating: MP3是否还在生成中（用于边生成边播放）
        
        Returns:
            str: playlist.m3u8的路径,转换失败返回None
        """
        # 获取转换锁,防止重复转换
        lock = self._get_conversion_lock(g.current_user.id)
        
        if not lock.acquire(blocking=False):
            print(f"[HLS转换] 用户 {g.current_user.id} 缓存正在转换中,跳过")
            # 等待转换完成
            lock.acquire()
            lock.release()
            return self.get_playlist_path(g.current_user.id)
        
        try:
            # 检查MP3文件是否存在
            if not os.path.exists(mp3_path):
                print(f"[HLS转换] MP3文件不存在: {mp3_path}")
                return None
            
            # 如果转换已经完成，直接返回
            if self.is_hls_ready(g.current_user.id):
                print(f"[HLS转换] MP3已转换完成，遇到重复请求")
                return self.get_playlist_path(g.current_user.id)

            # 创建HLS目录
            hls_dir = self.get_hls_dir(g.current_user.id)
            os.makedirs(hls_dir, exist_ok=True)
            
            playlist_path = self.get_playlist_path(g.current_user.id)
            segment_pattern = os.path.join(hls_dir, 'segment_%03d.ts')
                        
            # 决定转换模式
            existing_segments = self._count_segments(hls_dir)
            # 🔑 精确计算开始时间：从 playlist 读取实际时长
            start_time = self._get_playlist_duration(playlist_path) if existing_segments > 0 else 0
            start_time += timestamp
            
            if is_generating:
                # 增量转换模式：MP3正在生成且已有分段
                cmd = self._build_incremental_ffmpeg_cmd(
                    mp3_path, segment_pattern, playlist_path, start_time
                )
                # print(f"[HLS转换] 增量模式: 章节 {chapter_id} 从{start_time:.2f}秒开始, 分段编号{existing_segments}")
            else:
                # 全量转换模式：MP3已完成
                cmd = self._build_base_ffmpeg_cmd(
                    mp3_path, segment_pattern, playlist_path, start_time
                )
                # print(f"[HLS转换] 完整转换: 章节 {chapter_id} 从{start_time:.2f}秒开始")
            
            # print(f"[HLS转换] 命令: {' '.join(cmd)}")
            
            # 执行FFmpeg命令
            start_ts = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False
            )
            
            elapsed = time.time() - start_ts
            
            if result.returncode != 0:
                print(f"[HLS转换] ❌ 转换失败 (耗时 {elapsed:.2f}秒)")
                print(f"[HLS转换] stderr: {result.stderr}")
                return None
            
            print(f"[HLS转换] ✅ 转换成功 (耗时 {elapsed:.2f}秒): {playlist_path}")
            
            # 如果MP3还在生成中，需要移除ENDLIST标记
            if is_generating:
               self._remove_endlist_if_exists(playlist_path)
            
            # 验证转换结果
            if not is_generating and not self.is_hls_exists(g.current_user.id):
                print(f"[HLS转换] ⚠️  警告: playlist.m3u8未包含结束标记")
            
            return playlist_path
            
        except Exception as e:
            print(f"[HLS转换] 发生错误: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            lock.release()
    
    def convert_async(self, chapter_id, mp3_path, callback=None, is_generating=False):
        """
        异步转换MP3为HLS
        
        Args:
            chapter_id: 章节ID
            mp3_path: MP3文件路径
            callback: 回调函数 callback(success: bool, result: str)
            is_generating: MP3是否还在生成中
        """
        def worker():
            result = self.convert_mp3_to_hls(mp3_path, is_generating=is_generating)
            if callback:
                callback(result is not None, result)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread
    
    def get_hls_status(self, user_id):
        """
        获取HLS转换状态
        
        Returns:
            dict: {
                'ready': bool,          # 是否完全转换完成
                'exists': bool,         # playlist是否存在
                'segments': int,        # 已生成的分段数
                'duration': float       # 总时长(秒)
            }
        """
        playlist_path = self.get_playlist_path(user_id)
        
        status = {
            'ready': False,
            'exists': False,
            'segments': 0,
            'duration': 0.0
        }
        
        if not os.path.exists(playlist_path):
            return status
        
        status['exists'] = True
        
        try:
            with open(playlist_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # 检查是否完成
                status['ready'] = '#EXT-X-ENDLIST' in content
                
                # 统计分段数
                status['segments'] = content.count('#EXTINF:')
                
                # 计算总时长
                import re
                extinf_pattern = r'#EXTINF:([\d.]+),'
                durations = re.findall(extinf_pattern, content)
                status['duration'] = sum(float(d) for d in durations)
        
        except Exception as e:
            print(f"[HLS状态] 读取playlist失败: {e}")
        
        return status
    
    def cleanup_chapter_hls(self):
        """
        清理章节的HLS缓存
        
        Args:
            chapter_id: 章节ID
        """
        hls_dir = self.get_hls_dir(g.current_user.id)
        
        if not os.path.exists(hls_dir):
            return
        
        lock = self._get_conversion_lock(g.current_user.id)
        lock.acquire()
            
        try:
            import shutil
            shutil.rmtree(hls_dir)
            print(f"[HLS清理] 已删除用户 {g.current_user.id} 的HLS缓存")
        except Exception as e:
            print(f"[HLS清理] 删除失败: {e}")

        lock.release()

# 全局HLS管理器实例
_hls_manager = None

def get_hls_manager(hls_base_dir='hls_cache'):
    """获取全局HLS管理器实例"""
    global _hls_manager
    if _hls_manager is None:
        _hls_manager = HLSManager(hls_base_dir)
    return _hls_manager

def stream_chapter_hls(app, chapter_id, timestamp):
    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    # 权限校验
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        abort(403)
    
    hls_manager = get_hls_manager()
    hls_dir = hls_manager.get_hls_dir(g.current_user.id)
    mp3_path = os.path.join(app.config['AUDIO_FOLDER'], f'chapter_{chapter_id}.mp3')

    # 情况1: MP3已完成,且未进行HLS转换
    if chapter.audio_status == 'complete' and os.path.exists(mp3_path) and not hls_manager.is_hls_exists(g.current_user.id):
        print(f"[HLS路由] MP3已完成,且未进行HLS转换, 直接返回MP3文件: {mp3_path}")
        return send_file(mp3_path, mimetype='audio/mpeg')

    # 情况2: MP3已完成,但HLS转换已在进行中
    if chapter.audio_status == 'complete' and os.path.exists(mp3_path):
        print(f"[HLS转换] MP3已完成, 继续HLS转换: {mp3_path}")
        result = hls_manager.convert_mp3_to_hls(mp3_path, timestamp)
        if result:
            return send_from_directory(
                hls_dir,
                'playlist.m3u8',
                mimetype='application/vnd.apple.mpegurl'
            )
        else:
            abort(500, "HLS转换失败")
    
    # 情况3: MP3正在生成，继续转换
    if check_chapter_generating(g.current_user.id, chapter_id) and os.path.exists(mp3_path):
        # print(f"[HLS转换] MP3正在生成(大小:{file_size}),尝试转换现有部分")
        result = hls_manager.convert_mp3_to_hls(mp3_path, timestamp, is_generating=True)
        if result:
            return send_from_directory(
                hls_dir,
                'playlist.m3u8',
                mimetype='application/vnd.apple.mpegurl'
            )
        else:
            print(f"[HLS转换] 转换失败，返回404让客户端重试--1")
            abort(404, "HLS转换失败，请稍后重试")
    
    # 情况4: MP3尚未开始生成,启动生成流程
    print(f"[HLS转换] MP3尚未生成,启动音频生成: {mp3_path}")
    print(f"\n{'='*60}")
    print(f"开始生成章节 {chapter_id} 的音频")
    print(f"{'='*60}\n")
    
    # 启动音频生成(使用audio_generator模块)
    try:
        generate_chapter_audio(app, chapter_id, g.current_user.id, mp3_path)
    except Exception as e:
        print(f"[HLS路由] 启动音频生成失败: {e}")
        import traceback
        traceback.print_exc()
        abort(500, "启动音频生成失败")
    
    # 等待MP3文件开始生成
    import time
    for i in range(60):  # 最多等待30秒
        if os.path.exists(mp3_path):
            file_size = os.path.getsize(mp3_path)
            if file_size > 1024 * 50:  # 至少50KB
                print(f"[HLS路由] MP3已开始生成(大小:{file_size}),启动HLS转换")
                
                # 同步转换 (标记为正在生成，使用Event模式+增量转换)
                result = hls_manager.convert_mp3_to_hls(mp3_path, timestamp, is_generating=True)
                if result:
                    response = send_from_directory(
                        hls_dir,
                        'playlist.m3u8',
                        mimetype='application/vnd.apple.mpegurl'
                    )
                    response.headers['Cache-Control'] = 'no-cache'
                    return response
                else:
                    # 转换失败,返回404让客户端重试
                    print(f"[HLS路由] 转换失败，返回404让客户端重试--2")
                    abort(404, "HLS转换失败,请稍后重试")
        
        time.sleep(0.5)
    
    # 超时仍未生成
    abort(504, "音频生成超时,请稍后重试")