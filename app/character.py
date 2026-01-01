import json
import os
from models import Character, db
from flask import jsonify

def get_voice_config():
    """加载voice.json配置文件"""
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    voice_json_path = os.path.join(root_dir, 'voice.json')
    with open(voice_json_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def list_characters(novel_id=None):
    """
    获取角色列表
    
    Args:
        novel_id: 小说ID，如果提供则只返回该小说的角色
    
    Returns:
        dict: 包含角色列表的字典
    """
    query = Character.query
    if novel_id is not None:
        query = query.filter_by(novel_id=novel_id)
    
    characters = query.order_by(Character.id).all()
    
    return {
        "characters": [
            {
                "id": char.id,
                "name": char.name,
                "gender": char.gender,
                "personality": char.personality,
                "voice": char.voice
            }
            for char in characters
        ]
    }

def get_character(character_id):
    """
    获取单个角色信息
    
    Args:
        character_id: 角色ID
    
    Returns:
        dict: 角色信息
    """
    character = Character.query.get(character_id)
    if not character:
        return None
    
    return {
        "id": character.id,
        "name": character.name,
        "gender": character.gender,
        "personality": character.personality,
        "voice": character.voice
    }

def update_character(character_id, gender, personality):
    """
    更新角色信息
    
    Args:
        character_id: 角色ID
        gender: 性别
        personality: 个性
    
    Returns:
        dict: 操作结果
    """
    character = Character.query.get(character_id)
    if not character:
        return {"success": False, "message": "角色不存在"}
    
    voice_config = get_voice_config()
    
    # 验证性别和个性是否有效
    if gender not in voice_config.get('voices', {}):
        return {"success": False, "message": f"无效的性别: {gender}"}
    
    if personality not in voice_config['voices'][gender]:
        return {"success": False, "message": f"性别 {gender} 下没有个性: {personality}"}
    
    # 更新角色信息
    character.gender = gender
    character.personality = personality
    character.voice = voice_config['voices'][gender][personality]
    
    db.session.commit()
    
    return {"success": True, "message": "角色更新成功"}

def delete_character(character_id):
    """
    删除角色
    
    Args:
        character_id: 角色ID
    
    Returns:
        dict: 操作结果
    """
    character = Character.query.get(character_id)
    if not character:
        return {"success": False, "message": "角色不存在"}
    
    db.session.delete(character)
    db.session.commit()
    
    return {"success": True, "message": "角色删除成功"}

def get_voice_options():
    """
    获取voice.json中的性别和个性选项
    
    Returns:
        dict: 性别和个性选项
    """
    voice_config = get_voice_config()
    return voice_config.get('voices', {})
