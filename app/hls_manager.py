"""
HLS管理器 - 基于FFmpeg原生HLS功能
负责将MP3音频转换为HLS格式,支持混合方案(已生成/正在生成)
"""
import os
import subprocess
import threading
from threading import Lock
import time


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
    
    def get_hls_dir(self, chapter_id):
        """获取章节的HLS目录路径"""
        return os.path.join(self.hls_base_dir, f'chapter_{chapter_id}')
    
    def get_playlist_path(self, chapter_id):
        """获取章节的playlist.m3u8路径"""
        return os.path.join(self.get_hls_dir(chapter_id), 'playlist.m3u8')
    
    def is_hls_ready(self, chapter_id):
        """检查HLS是否已经转换完成"""
        playlist_path = self.get_playlist_path(chapter_id)
        if not os.path.exists(playlist_path):
            return False
        
        # 检查playlist.m3u8是否包含结束标记
        try:
            with open(playlist_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return '#EXT-X-ENDLIST' in content
        except:
            return False
    
    def _get_conversion_lock(self, chapter_id):
        """获取章节的转换锁"""
        with self._global_lock:
            if chapter_id not in self._conversion_locks:
                self._conversion_locks[chapter_id] = Lock()
            return self._conversion_locks[chapter_id]
    
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
                
                print(f"[HLS管理器] 已移除ENDLIST标记，支持边生成边播放")
        except Exception as e:
            print(f"[HLS管理器] 移除ENDLIST失败: {e}")
    
    def _build_base_ffmpeg_cmd(self, mp3_path, segment_pattern, playlist_path, playlist_type, start_time):
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
            '-i', mp3_path,
            '-c:a', 'copy',                     # 直接复制MP3流，不转码
            '-f', 'hls',                        # 输出格式HLS
            '-hls_time', '6',                   # 每段6秒
            '-hls_list_size', '0',              # 保留所有分段
            '-hls_playlist_type', playlist_type, # event=无ENDLIST, vod=有ENDLIST
            '-hls_segment_type', 'mpegts',      # 使用MPEG-TS容器
            '-hls_flags', 'independent_segments+append_list', # 🔑 追加模式，自动计算编号
            '-hls_segment_filename', segment_pattern,
            '-y',                               # 覆盖已存在的文件
            playlist_path
        ]
    
    def _build_incremental_ffmpeg_cmd(self, mp3_path, segment_pattern, playlist_path, 
                                       start_time, start_segment):
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
        # 注意：-hls_start_number 在 FFmpeg 6.1 中不支持
        # 使用 append_list 时，FFmpeg 会自动从 playlist 读取已有分段编号
        return [
            'ffmpeg',
            '-ss', str(start_time),             # 🔑 跳过已转换部分
            '-i', mp3_path,
            '-c:a', 'copy',
            '-f', 'hls',
            '-hls_time', '6',
            '-hls_list_size', '0',
            # '-hls_playlist_type', 'live',      # live模式（无ENDLIST）
            '-hls_segment_type', 'mpegts',
            '-hls_flags', 'independent_segments+append_list',  # 🔑 追加模式，自动计算编号
            '-hls_segment_filename', segment_pattern,
            playlist_path
        ]
    
    def convert_mp3_to_hls(self, chapter_id, mp3_path, timestamp, force=False, is_generating=False):
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
        lock = self._get_conversion_lock(chapter_id)
        
        if not lock.acquire(blocking=False):
            print(f"[HLS转换] 章节 {chapter_id} 正在转换中,跳过")
            # 等待转换完成
            lock.acquire()
            lock.release()
            return self.get_playlist_path(chapter_id)
        
        try:
            # 检查MP3文件是否存在
            if not os.path.exists(mp3_path):
                print(f"[HLS转换] MP3文件不存在: {mp3_path}")
                return None
            
            # 创建HLS目录
            hls_dir = self.get_hls_dir(chapter_id)
            os.makedirs(hls_dir, exist_ok=True)
            
            playlist_path = self.get_playlist_path(chapter_id)
            segment_pattern = os.path.join(hls_dir, 'segment_%03d.ts')
            
            # 检查是否已转换完成
            if not force and not is_generating and self.is_hls_ready(chapter_id):
                print(f"[HLS转换] 章节 {chapter_id} 已经转换完成: {playlist_path}")
                return playlist_path
            
            # 决定转换模式
            existing_segments = self._count_segments(hls_dir)
            # 🔑 精确计算开始时间：从 playlist 读取实际时长
            start_time = self._get_playlist_duration(playlist_path) if existing_segments > 0 else 0
            start_time += timestamp
            
            if is_generating:
                # 增量转换模式：MP3正在生成且已有分段
                cmd = self._build_incremental_ffmpeg_cmd(
                    mp3_path, segment_pattern, playlist_path, 
                    start_time, existing_segments
                )
                print(f"[HLS转换] 增量模式: 从{start_time:.2f}秒开始, 分段编号{existing_segments}")
            else:
                # 全量转换模式：MP3已完成
                playlist_type = 'vod'
                cmd = self._build_base_ffmpeg_cmd(
                    mp3_path, segment_pattern, playlist_path, playlist_type, start_time
                )
                print(f"[HLS转换] 完整转换")
            
            print(f"[HLS转换] 开始转换章节 {chapter_id}: {mp3_path}")
            print(f"[HLS转换] 命令: {' '.join(cmd)}")
            
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
            if not is_generating and not self.is_hls_ready(chapter_id):
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
            result = self.convert_mp3_to_hls(chapter_id, mp3_path, is_generating=is_generating)
            if callback:
                callback(result is not None, result)
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread
    
    def convert_partial_mp3_to_hls(self, chapter_id, mp3_path):
        """
        将正在生成的MP3部分转换为HLS（实时追加模式）
        
        注意: 这个方法会持续监听MP3文件的增长,直到文件生成完成
        适用于边生成边播放的场景
        
        Args:
            chapter_id: 章节ID
            mp3_path: MP3文件路径(可能正在增长)
        
        Returns:
            str: playlist.m3u8的路径
        """
        hls_dir = self.get_hls_dir(chapter_id)
        os.makedirs(hls_dir, exist_ok=True)
        
        playlist_path = self.get_playlist_path(chapter_id)
        segment_pattern = os.path.join(hls_dir, 'segment_%03d.ts')
        
        print(f"[HLS实时转换] 开始监听MP3文件: {mp3_path}")
        
        # 使用FFmpeg的实时模式
        # 注意: 这需要MP3文件以追加模式写入
        cmd = [
            'ffmpeg',
            '-re',                              # 实时模式
            '-i', mp3_path,
            '-c:a', 'copy',
            '-f', 'hls',
            '-hls_time', '6',
            '-hls_list_size', '0',
            '-hls_flags', 'append_list+split_by_time',  # 实时追加模式
            '-hls_segment_type', 'mpegts',
            '-hls_segment_filename', segment_pattern,
            playlist_path
        ]
        
        print(f"[HLS实时转换] 命令: {' '.join(cmd)}")
        
        try:
            # 非阻塞方式启动FFmpeg进程
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            print(f"[HLS实时转换] FFmpeg进程已启动 (PID: {process.pid})")
            
            # 返回playlist路径,让客户端可以开始播放
            return playlist_path
            
        except Exception as e:
            print(f"[HLS实时转换] 启动失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def get_hls_status(self, chapter_id):
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
        playlist_path = self.get_playlist_path(chapter_id)
        
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
    
    def cleanup_chapter_hls(self, chapter_id):
        """
        清理章节的HLS缓存
        
        Args:
            chapter_id: 章节ID
        """
        hls_dir = self.get_hls_dir(chapter_id)
        
        if not os.path.exists(hls_dir):
            return
        
        lock = self._get_conversion_lock(chapter_id)
        lock.acquire()
            
        try:
            import shutil
            shutil.rmtree(hls_dir)
            print(f"[HLS清理] 已删除章节 {chapter_id} 的HLS缓存")
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
