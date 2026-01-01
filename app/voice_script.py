import json
from llm_client import LLMClient
from models import Character, db

def generate_voice_script(content, stream=False, llm_api_key=None, llm_base_url=None, llm_model=None, novel_id=None):
    """
    调用LLM生成配音脚本，并进行后处理转换
    
    Args:
        content (str): 待处理的文本内容
        stream (bool): 是否启用流式输出
        llm_api_key (str): LLM API密钥（可选，用于小说专有配置）
        llm_base_url (str): LLM Base URL（可选，用于小说专有配置）
        llm_model (str): LLM模型名称（可选，用于小说专有配置）
        novel_id (int): 小说ID（可选，用于关联角色到特定小说）
        
    Returns:
        list: 转换后的配音脚本列表
    """
    # 创建LLM客户端，使用传入的参数（如果提供）
    llm_client = LLMClient(api_key=llm_api_key, base_url=llm_base_url, model=llm_model)
    
    # 调用LLM生成配音脚本（无论是否流式，都会返回结果）
    voice_script = llm_client.generate_voice_script(content, stream=stream)
    
    # 转换配音脚本为目标格式
    converted_script = convert_voice_script(voice_script, novel_id=novel_id)
    
    return converted_script

def convert_voice_script(voice_script, novel_id=None):
    """
    将LLM返回的配音脚本转换为目标格式
    
    Args:
        voice_script (dict): LLM返回的配音脚本
        novel_id (int): 小说ID（可选，用于关联角色到特定小说）
        
    Returns:
        list: 转换后的配音脚本列表
    """
    # 加载voice.json配置文件
    import os
    # 获取项目根目录
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    voice_json_path = os.path.join(root_dir, 'voice.json')
    with open(voice_json_path, 'r', encoding='utf-8') as f:
        voice_config = json.load(f)
    
    # 处理角色表
    if 'charactors' in voice_script:
        for char in voice_script['charactors']:
            # 检查数据库中是否已存在该角色
            query = Character.query.filter_by(name=char['name'])
            if novel_id is not None:
                query = query.filter_by(novel_id=novel_id)
            existing_character = query.first()
            
            # 如果数据库中没有该角色，则添加到数据库
            if not existing_character:
                # 获取角色的性别和个性
                gender = char.get('gender', 'Male')
                personality = char.get('personalities', '')
                
                # 从voice.json中获取对应的语音
                voice = None
                if gender in voice_config['voices'] and personality in voice_config['voices'][gender]:
                    voice = voice_config['voices'][gender][personality]
                else:
                    # 如果找不到匹配的语音，使用默认旁白语音
                    voice = voice_config.get('旁白', 'zh-CN-YunjianNeural')
                    print(f"警告: 角色 {char['name']} 的性别 {gender} 或个性 {personality} 在voice.json中未找到，使用默认旁白语音")
                
                new_character = Character(
                    name=char['name'],
                    gender=gender,
                    personality=personality,
                    voice=voice,
                    novel_id=novel_id
                )                
                db.session.add(new_character)
        
        # 提交数据库更改
        db.session.commit()
    
    # 转换分段脚本
    converted_segments = []
    
    # 如果有segments字段，则进行转换
    if 'segments' in voice_script:
        for segment in voice_script['segments']:
            # 清理文本内容，移除可能导致JSON解析错误的字符
            text_content = segment['text']
            # 清理控制字符（保留换行符和制表符）
            text_content = ''.join(char for char in text_content if char.isprintable() or char in '\n\t')
            
            # 创建转换后的段落
            converted_segment = {
                "desc": segment['charactor'],
                "text": text_content
            }
            
            # 如果是旁白
            if segment['charactor'] == '旁白':
                converted_segment['voice'] = voice_config['旁白']
                converted_segment['rate'] = voice_config['default-rate']
            else:
                # 如果是角色对白，从数据库中获取角色信息
                character = Character.query.filter_by(name=segment['charactor']).first()
                if character and character.voice:
                    converted_segment['voice'] = character.voice
                else:
                    # 如果数据库中没有该角色，使用默认语音
                    converted_segment['voice'] = voice_config['旁白']  # 使用旁白语音作为默认
            
            # 添加LLM推荐的参数（如果有）
            # 如果rate、pitch、volume的值（不包括单位）曾0，则不包含在JSON中
            if 'rate' in segment:
                # 提取rate的数值部分
                rate_value = segment['rate'].rstrip('%')
                if rate_value and rate_value not in ['0', '+0', '-0']:
                    # 检查是否为旁白且rate小于最小值
                    if segment['charactor'] == '旁白':
                        # 获取旁白的最小rate值
                        min_rate_value = voice_config.get('旁白-min-rate', '0%').rstrip('%')
                        # 安全地转换为浮点数进行比较
                        try:
                            if int(rate_value) < int(min_rate_value):
                                converted_segment['rate'] = voice_config['旁白-min-rate']
                            else:
                                converted_segment['rate'] = segment['rate']
                        except ValueError:
                            # 如果转换失败，使用原始值
                            converted_segment['rate'] = segment['rate']
                    else:
                        converted_segment['rate'] = segment['rate']
            
            if 'pitch' in segment:
                # 提取pitch的数值部分
                pitch_value = segment['pitch'].rstrip('Hz')
                if pitch_value and pitch_value not in ['0', '+0', '-0']:
                    converted_segment['pitch'] = segment['pitch']
            
            if 'volume' in segment:
                # 提取volume的数值部分
                volume_value = segment['volume'].rstrip('%')
                if volume_value and volume_value not in ['0', '+0', '-0']:
                    converted_segment['volume'] = segment['volume']
            
            converted_segments.append(converted_segment)
    
    return converted_segments
