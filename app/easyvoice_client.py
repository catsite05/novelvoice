import requests
import json
import os

class EasyVoiceClient:
    """
    EasyVoice API客户端，用于调用本地EasyVoice服务生成音频
    """
    
    def __init__(self, base_url: str = None):
        """
        初始化EasyVoice客户端
        
        Args:
            base_url (str): EasyVoice服务的基础URL，默认为http://localhost:3000
        """
        self.base_url = base_url or os.getenv('EASYVOICE_BASE_URL', 'http://localhost:3000')
    
    def generate_audio_stream(self, voice_script: list):
        """
        调用EasyVoice API流式生成音频（生成器模式）
        
        Args:
            voice_script (list): 配音脚本内容
            
        Yields:
            bytes: 音频数据块
        """
        # 构建API端点URL
        url = f"{self.base_url}/api/v1/tts/generateJson"
        
        # 构建请求数据
        data = {"data": voice_script}
        headers = {'Content-Type': 'application/json'}
        
        print(f"\n[EasyVoice] 开始流式调用: {url}")
        print(f"[EasyVoice] 脚本段落数: {len(voice_script)}")
        
        try:
            # 关键：stream=True 启用流式响应
            response = requests.post(
                url,
                headers=headers,
                json=data,
                stream=True,  # 启用流式传输
                timeout=120
            )
            response.raise_for_status()
            
            print(f"[EasyVoice] 开始接收流式数据...")
            
            # 逐块读取并立即 yield
            chunk_count = 0
            total_size = 0
            for chunk in response.iter_content(chunk_size=4096):
                if chunk:
                    chunk_count += 1
                    total_size += len(chunk)
                    yield chunk
                    # if chunk_count % 10 == 0:
                    #     print(f"[EasyVoice] 已接收 {chunk_count} 个块，共 {total_size} 字节")
            
            print(f"[EasyVoice] 流式传输完成，总计 {total_size} 字节\n")
            
        except requests.exceptions.RequestException as e:
            print(f"\n❌ [EasyVoice] 流式调用失败: {str(e)}")
            raise
    
    def generate_audio(self, voice_script: list, output_path: str) -> bool:
        """
        调用EasyVoice API生成音频文件（保留兼容性）
        
        Args:
            voice_script (list): 配音脚本内容
            output_path (str): 输出音频文件路径
            
        Returns:
            bool: 是否成功生成音频文件
        """
        # 构建API端点URL
        url = f"{self.base_url}/api/v1/tts/generateJson"
        
        # 构建请求数据
        data = {
            "data": voice_script
        }
        
        # 设置请求头
        headers = {
            'Content-Type': 'application/json'
        }
        
        # ===== 调试信息开始 =====
        print("\n" + "="*70)
        print("【EasyVoice 调试信息】")
        print("="*70)
        print(f"EasyVoice URL: {url}")
        print(f"输出文件: {output_path}")
        print(f"\n配音脚本内容（共{len(voice_script)}个段落）：")
        print("-"*70)
        
        # 打印完整的JSON脚本
        try:
            script_json = json.dumps(data, ensure_ascii=False, indent=2)
            print(script_json)
        except Exception as e:
            print(f"无法序列化脚本: {e}")
            print(f"原始脚本: {voice_script}")
        
        print("-"*70)
        print(f"请求头: {headers}")
        print("="*70 + "\n")
        # ===== 调试信息结束 =====
        
        try:
            # 发送POST请求到EasyVoice API
            print("正在调用EasyVoice API...")
            response = requests.post(
                url, 
                headers=headers, 
                json=data  # 直接使用json参数，requests会自动序列化
            )
            
            # 打印响应状态
            print(f"\nEasyVoice 响应状态码: {response.status_code}")
            print(f"EasyVoice 响应头: {dict(response.headers)}")
            
            # 检查响应状态
            response.raise_for_status()
            
            # 打印响应内容类型和大小
            content_length = len(response.content)
            print(f"EasyVoice 响应内容大小: {content_length} 字节")
            
            # 如果响应内容很小，可能是错误消息
            if content_length < 1000:
                try:
                    error_text = response.text
                    print(f"\n警告：响应内容较小，可能是错误信息：")
                    print(error_text)
                except:
                    pass
            
            # 将响应内容保存到音频文件
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            print(f"\n✅ 音频文件生成成功: {output_path}\n")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"\n❌ 调用EasyVoice API时发生错误: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"错误响应内容: {e.response.text}")
            print()
            return False
        except IOError as e:
            print(f"\n❌ 保存音频文件时发生错误: {str(e)}\n")
            return False