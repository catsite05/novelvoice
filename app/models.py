from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class Novel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=True)
    file_path = db.Column(db.String(300), nullable=False)
    upload_date = db.Column(db.DateTime, nullable=False)
    
    def __repr__(self):
        return f'<Novel {self.title}>'


class Chapter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    start_position = db.Column(db.Integer, nullable=False)
    audio_file_path = db.Column(db.String(300), nullable=True)
    
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