#!/usr/bin/env python3
import getpass
import os
import sys

# 确保可以导入 app 包
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(BASE_DIR, 'app')
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from app import app
from models import db, User
from werkzeug.security import generate_password_hash


def main():
    print("创建超级用户")

    if len(sys.argv) < 3:
        print("用法: python create_superuser.py <用户名> <密码>")
        return

    username = sys.argv[1].strip()
    password = sys.argv[2]

    if not username:
        print("用户名不能为空")
        return

    if not password:
        print("密码不能为空")
        return

    with app.app_context():
        db.create_all()
        # 检查是否已存在同名用户
        if User.query.filter_by(username=username).first():
            print("该用户名已存在")
            return

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            is_superuser=True,
        )
        db.session.add(user)
        db.session.commit()

        print(f"超级用户 '{username}' 创建成功")


if __name__ == '__main__':
    main()
