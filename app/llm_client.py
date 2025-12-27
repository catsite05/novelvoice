import json
import requests
import os
import re
from typing import Dict, Any

class LLMClient:
    """
    LLM客户端，用于调用大语言模型API生成配音脚本
    """
    
    def __init__(self, api_key: str = None, base_url: str = None, model: str = None):
        """
        初始化LLM客户端
        
        Args:
            api_key (str): API密钥
            base_url (str): API基础URL
            model (str): 模型名称
        """
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.base_url = base_url or os.getenv('LLM_BASE_URL', 'https://api.openai.com/v1')
        self.model = model or os.getenv('LLM_MODEL', 'gpt-3.5-turbo')
        
        # 默认请求头
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
    
    def generate_voice_script(self, content: str, stream: bool = False) -> Dict[str, Any]:
        """
        调用LLM生成配音脚本
        
        Args:
            content (str): 待处理的文本内容
            
        Returns:
            dict: 包含角色表和分段的配音脚本
        """
        # 构建提示词
        prompt = self._build_prompt(content)
        
        # 构建请求数据
        data = {
            'model': self.model,  # 使用配置的模型
            'messages': [
                {'role': 'system', 'content': '你是一个专业的有声书制作助手，擅长分析文本并生成配音脚本。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.7,
            'max_tokens': 20000,
            'stream': stream  # 是否启用流式输出
        }
        
        # 打印LLM参数
        # print(f"[LLM] 参数: {self.api_key}, {self.base_url}, {self.model}", flush=True)

        # 发送请求到LLM API
        # 增加超时时间以适应大模型处理时间
        try:
            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=self.headers,
                json=data,
                timeout=300,  # 增加到5分钟超时
                stream=stream  # 启用requests的流式模式
            )
            
            # 检查响应状态
            response.raise_for_status()
            
            generated_text = ""
            
            # 如果启用流式输出，逐块处理响应
            if stream:
                print("\n开始流式输出LLM响应:", flush=True)
                print("-" * 50, flush=True)
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        # 处理SSE格式的数据块
                        if decoded_line.startswith('data: '):
                            data_content = decoded_line[6:].strip()  # 移除'data: '前缀
                            if data_content == '[DONE]':
                                break
                            try:
                                chunk_data = json.loads(data_content)
                                if 'choices' in chunk_data and len(chunk_data['choices']) > 0:
                                    delta = chunk_data['choices'][0].get('delta', {})
                                    content_chunk = delta.get('content', '')
                                    if content_chunk:
                                        print(content_chunk, end='', flush=True)  # 实时打印内容
                                        generated_text += content_chunk
                            except json.JSONDecodeError as e:
                                # 忽略无法解析的行
                                pass
                print("\n" + "-" * 50, flush=True)
                print("流式输出结束\n", flush=True)
            else:
                # 非流式模式：解析响应
                result = response.json()
                # 提取生成的文本
                generated_text = result['choices'][0]['message']['content']
                # print(f"[LLM] 生成的文本: {generated_text}", flush=True)
            
            # 清理文本中的控制字符和非法字符
            cleaned_text = self._clean_text_for_json(generated_text)
            
            # 尝试解析JSON
            try:
                voice_script = json.loads(cleaned_text)
                return voice_script
            except json.JSONDecodeError:
                # 如果LLM返回的不是有效的JSON，尝试从中提取JSON部分
                # 这种情况可能发生在LLM在JSON前后添加了其他文本
                json_start = cleaned_text.find('{')
                json_end = cleaned_text.rfind('}') + 1
                
                if json_start != -1 and json_end > json_start:
                    json_text = cleaned_text[json_start:json_end]
                    try:
                        voice_script = json.loads(json_text)
                        return voice_script
                    except json.JSONDecodeError:
                        raise Exception(f"LLM返回的文本无法解析为JSON: {generated_text}")
                else:
                    raise Exception(f"LLM返回的文本无法解析为JSON: {generated_text}")
                    
        except requests.exceptions.RequestException as e:
            raise Exception(f"调用LLM API时发生错误: {str(e)}")
        except KeyError as e:
            raise Exception(f"LLM API响应格式不正确: {str(e)}")
    
    def _clean_text_for_json(self, text: str) -> str:
        """
        清理文本中的控制字符和非法字符，防止JSON解析错误
        
        Args:
            text (str): 待清理的文本
            
        Returns:
            str: 清理后的文本
        """
        # 移除控制字符（保留换行符、制表符、回车符）
        # 控制字符范围: \x00-\x1F 和 \x7F-\x9F
        # 保留: \n (\x0A), \r (\x0D), \t (\x09)
        cleaned = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]', '', text)
        
        # 移除零宽字符和其他不可见字符
        cleaned = re.sub(r'[\u200B-\u200D\uFEFF]', '', cleaned)
        
        return cleaned
    
    def _build_prompt(self, content: str) -> str:
        """
        构建发送给LLM的提示词
        
        Args:
            content (str): 待处理的文本内容
            
        Returns:
            str: 完整的提示词
        """
        prompt = f"""
我希望你根据以下文字内容，为文字配音提供优化建议。任务包括：
1. 梳理文字中出现的角色表。
2. 将文字按角色、旁白分割。角色部分是某个角色说的对白，旁白部分则包括除角色对白之外的其余内容。
3. 为每段推荐合理的"rate"（语速）、"volume"（音量）、"pitch"（音调）参数。
4. 请不要遗漏语句以及保证语句的顺序。
5. 返回结果为 JSON 格式。

### 参数说明
- rate: 语速调整，百分比形式，默认 +0%（正常），如 "+50%"（加快 50%），"-20%"（减慢 20%）。
- volume: 音量调整，百分比形式，默认 +0%（正常），如 "+20%"（增 20%），"-10%"（减 10%）。
- pitch: 音调调整，默认 +0Hz（正常），如 "+10Hz"（提高 10 赫兹），"-5Hz"（降低 5 赫兹）。

### 最终返回JSON格式
{{
  "charactors": [
    {{
      "name": "角色的名称",
      "gender": "角色的性别，Male 或 Female",
      "personalities": "角色的个性，如果性别是Male，从: Passion、Lively、Sunshine、Cute、Professional、Reliable 中选择一项；如果性别是Female，从：Warm、Lively、Humorous、Bright 中选择一项"
    }}
  ],
  "segments": [
    {{
      "charactor": "角色名或旁白",
      "rate": "语速",
      "volume": "音量",
      "pitch": "音调",
      "text": "文本段落，如果charactor是角色名，则文本段落仅包含对白内容"
    }}
  ]
}}

### 角色对话引导语的处理方法
角色对话引导语需分不同情况进行处理。
（1） 如果引导语中包含有角色的动作、表情、心情等内容，需要完整保留引导语并单独放在一个旁白片段中。
举例说明。
原文：苏剑笑微笑着道："你明天就在客栈中安心等我的好消息吧。"
应生成两个片段：
    {{
      "charactor": "旁白",
      "text": "苏剑笑微笑着道"
    }},
    {{
      "charactor": "苏剑笑",
      "text": "“你明天就在客栈中安心等我的好消息吧。”"
    }}
原文：李素云白了他一眼，微微有些生气地道：“我只是想听听你的看法。”
应生成两个片段：
    {{
      "charactor": "旁白",
      "text": "李素云白了他一眼，微微有些生气地道"
    }},
    {{
      "charactor": "李素云",
      "text": "“我只是想听听你的看法。”"
    }}

（2）如果引导语只是简单的XX道、XX说，则需将引导语忽略。
举例说明。
原文：李素云道："我不需要你做什么，只是想知道，倘若有一天我死了，你会喜欢上其他女孩子么？"
应只生成一个片段：
     {{
      "charactor": "李素云",
      "text": "“我不需要你做什么，只是想知道，倘若有一天我死了，你会喜欢上其他女孩子么？”"
    }}

### 待处理内容
{content}

请严格按照指定的JSON格式返回结果，不要添加任何额外的文本或解释。
"""
        
        return prompt