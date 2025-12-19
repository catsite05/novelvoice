#!/usr/bin/env python3
"""
清空 Character 表的所有数据（不删除表结构）
"""
import sys
import os

# 将 app 目录添加到路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

from flask import Flask
from models import db, Character
from config import Config

# 创建 Flask 应用
app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

def clear_characters():
    """清空 Character 表的所有数据"""
    with app.app_context():
        try:
            # 查询当前角色数量
            count_before = Character.query.count()
            print(f"清空前角色表中有 {count_before} 条记录")
            
            # 删除所有角色数据
            Character.query.delete()
            db.session.commit()
            
            # 确认清空结果
            count_after = Character.query.count()
            print(f"清空后角色表中有 {count_after} 条记录")
            print("✓ 角色表数据已成功清空！")
            
        except Exception as e:
            db.session.rollback()
            print(f"✗ 清空角色表时出错: {str(e)}")
            sys.exit(1)

if __name__ == '__main__':
    clear_characters()
