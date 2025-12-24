import edge_tts
import asyncio


class EdgeTTSClient:
    """
    Edge TTS客户端，用于直接调用edge-tts生成音频
    """
    
    def __init__(self):
        """
        初始化EdgeTTS客户端
        """
        pass
    
    def generate_audio_stream(self, voice_script: list, cancel_event=None):
        """
        调用Edge TTS API流式生成音频（生成器模式）
        逐段落生成音频并流式返回
        
        Args:
            voice_script (list): 配音脚本内容，每个元素包含：
                - desc: 角色描述
                - text: 要转换的文本
                - voice: Azure TTS语音ID
                - rate: 语速（可选）
                - pitch: 音调（可选）
                - volume: 音量（可选）
            cancel_event: threading.Event 对象，用于取消生成
                
        Yields:
            bytes: 音频数据块
        """
        print(f"\n[EdgeTTS] 开始流式生成音频")
        print(f"[EdgeTTS] 脚本段落数: {len(voice_script)}")
        
        loop = None
        async_gen = None
        
        async def generate_all_segments():
            """异步生成所有段落的音频"""
            for i, segment in enumerate(voice_script):
                # 检查取消信号
                if cancel_event and cancel_event.is_set():
                    print(f"[EdgeTTS] 收到取消信号，停止生成")
                    return
                    
                # print(f"\n[EdgeTTS] 正在处理第 {i+1}/{len(voice_script)} 段...")
                
                text = segment.get('text', '')
                voice = segment.get('voice', 'zh-CN-YunjianNeural')
                rate = segment.get('rate', '+0%')
                pitch = segment.get('pitch', '+0Hz')
                volume = segment.get('volume', '+0%')
                
                # 如果文本为空，跳过
                if not text or not text.strip():
                    print(f"[EdgeTTS] 第 {i+1} 段文本为空，跳过")
                    continue
                
                # print(f"[EdgeTTS] 生成音频: voice={voice}, rate={rate}, pitch={pitch}, volume={volume}")
                # print(f"[EdgeTTS] 文本长度: {len(text)} 字符")
                
                # 重试机制：最多重试3次
                max_retries = 3
                retry_delay = 2
                
                for attempt in range(max_retries):
                    # 再次检查取消信号
                    if cancel_event and cancel_event.is_set():
                        print(f"[EdgeTTS] 收到取消信号，停止生成")
                        return
                        
                    try:
                        # 创建Communicate对象并流式生成音频
                        communicate = edge_tts.Communicate(text, voice, rate=rate, volume=volume, pitch=pitch)
                        chunk_count = 0
                        
                        async for chunk in communicate.stream():
                            if chunk["type"] == "audio":
                                chunk_count += 1
                                yield chunk["data"]
                                
                            # 检查取消信号
                            if cancel_event and cancel_event.is_set():
                                print(f"[EdgeTTS] 收到取消信号，停止生成")
                                return
                        
                        # print(f"[EdgeTTS] 第 {i+1} 段生成完成，共 {chunk_count} 个数据块")
                        
                        # 成功后添加短暂延迟，避免请求过快
                        # if i < len(voice_script) - 1:
                        #     await asyncio.sleep(0.5)
                        
                        break  # 成功则跳出重试循环
                        
                    except Exception as e:
                        error_msg = str(e)
                        
                        # 检查是否是403错误
                        if "403" in error_msg or "Invalid response status" in error_msg:
                            if attempt < max_retries - 1:
                                wait_time = retry_delay * (attempt + 1)
                                print(f"[EdgeTTS] 第 {i+1} 段遇到403错误，{wait_time}秒后重试 (尝试 {attempt + 1}/{max_retries})...")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                print(f"[EdgeTTS] 第 {i+1} 段重试{max_retries}次后仍失败: {error_msg}")
                                print(f"[EdgeTTS] 提示：edge-tts可能遇到微软服务限流，建议：")
                                print(f"[EdgeTTS]   1. 等待几分钟后重试")
                                print(f"[EdgeTTS]   2. 或设置环境变量 USE_EASYVOICE=1 切换到EasyVoice")
                                raise
                        else:
                            print(f"[EdgeTTS] 第 {i+1} 段生成失败: {error_msg}")
                            raise
            
            print(f"\n[EdgeTTS] 所有段落生成完成\n")
        
        # 运行异步生成器并同步yield结果
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # 创建异步生成器
                async_gen = generate_all_segments()
                
                # 同步地从异步生成器中获取数据并yield
                while True:
                    try:
                        chunk = loop.run_until_complete(async_gen.__anext__())
                        yield chunk
                    except StopAsyncIteration:
                        break
                    except GeneratorExit:
                        # 生成器被关闭（客户端断开或取消）
                        print(f"[EdgeTTS] 生成器被关闭")
                        break
                        
            finally:
                # 确保异步生成器被正确关闭
                if async_gen is not None:
                    try:
                        loop.run_until_complete(async_gen.aclose())
                    except Exception as e:
                        print(f"[EdgeTTS] 关闭异步生成器时出错: {e}")
                
                # 关闭事件循环前等待所有任务完成
                if loop and not loop.is_closed():
                    try:
                        # 取消所有待处理的任务
                        pending = asyncio.all_tasks(loop)
                        for task in pending:
                            task.cancel()
                        
                        # 等待所有任务完成或被取消
                        if pending:
                            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    except Exception as e:
                        print(f"[EdgeTTS] 清理任务时出错: {e}")
                    finally:
                        loop.close()
                
        except GeneratorExit:
            # 生成器被外部关闭，正常退出
            print(f"[EdgeTTS] 流式生成被取消")
        except Exception as e:
            print(f"\n❌ [EdgeTTS] 流式生成失败: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    def generate_audio(self, voice_script: list, output_path: str) -> bool:
        """
        调用Edge TTS API生成音频文件（保留兼容性）
        
        Args:
            voice_script (list): 配音脚本内容
            output_path (str): 输出音频文件路径
            
        Returns:
            bool: 是否成功生成音频文件
        """
        print(f"\n[EdgeTTS] 生成音频文件: {output_path}")
        print(f"[EdgeTTS] 脚本段落数: {len(voice_script)}")
        
        try:
            # 打开输出文件
            with open(output_path, 'wb') as f:
                # 使用流式生成方法
                for chunk in self.generate_audio_stream(voice_script):
                    f.write(chunk)
            
            print(f"\n✅ 音频文件生成成功: {output_path}\n")
            return True
            
        except Exception as e:
            print(f"\n❌ 生成音频文件时发生错误: {str(e)}\n")
            import traceback
            traceback.print_exc()
            return False
