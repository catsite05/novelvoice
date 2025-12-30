from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        return f'<User {self.username}>'


class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=True)
    file_path = db.Column(db.String(300), nullable=False)
    upload_date = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    last_read_chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=True)  # 最后阅读的章节
    
    # LLM专有配置参数
    llm_api_key = db.Column(db.String(500), nullable=True)  # 小说专有的LLM API密钥
    llm_base_url = db.Column(db.String(500), nullable=True)  # 小说专有的LLM Base URL
    llm_model = db.Column(db.String(100), nullable=True)  # 小说专有的LLM模型名称

    user = db.relationship('User', backref=db.backref('novels', lazy=True))
    last_read_chapter = db.relationship('Chapter', foreign_keys=[last_read_chapter_id], post_update=True)
    
    def __repr__(self):
        return f'<Novel {self.title}>'


class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    start_position = db.Column(db.Integer, nullable=False)
    audio_file_path = db.Column(db.String(300), nullable=True)
    audio_status = db.Column(db.String(20), nullable=True)  # 'generating', 'complete', 'failed'
    
    # Foreign key to Novel
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    
    def __repr__(self):
        return f'<Chapter {self.title}>'


class Character(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    gender = db.Column(db.String(10), nullable=False)  # male or female
    personality = db.Column(db.String(50), nullable=False)  # From the given options
    voice = db.Column(db.String(100), nullable=True)  # Voice identifier from voice.json
    
    def __repr__(self):
        return f'<Character {self.name}>'


class AudioProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    novel_id = db.Column(db.Integer, db.ForeignKey('novel.id'), nullable=False)
    chapter_id = db.Column(db.Integer, db.ForeignKey('chapter.id'), nullable=False)
    position = db.Column(db.Float, nullable=False, default=0.0)  # 播放位置（秒）
    updated_at = db.Column(db.DateTime, nullable=False)
    
    user = db.relationship('User', backref=db.backref('audio_progress', lazy=True))
    novel = db.relationship('Novel', backref=db.backref('audio_progress', lazy=True))
    chapter = db.relationship('Chapter', backref=db.backref('audio_progress', lazy=True))
    
    def __repr__(self):
        return f'<AudioProgress user={self.user_id} novel={self.novel_id} chapter={self.chapter_id} position={self.position}>'