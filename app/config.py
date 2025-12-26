import os
from datetime import timedelta

# Get the directory of the config file (app/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
root_dir = os.path.dirname(current_dir)

class Config:
    # Database configuration
    INSTANCE_FOLDER = os.path.join(root_dir, 'instance')
    if not os.path.exists(INSTANCE_FOLDER):
        os.makedirs(INSTANCE_FOLDER)

    SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(INSTANCE_FOLDER, 'novelvoice.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session / security configuration
    SECRET_KEY = os.environ.get('SECRET_KEY', 'novelvoice-secret-key')
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Upload folder configuration (使用绝对路径)
    UPLOAD_FOLDER = os.path.join(root_dir, 'uploads')
    AUDIO_FOLDER = os.path.join(root_dir, 'audio')
    HLS_FOLDER = os.path.join(root_dir, 'hls_cache')  # HLS缓存目录
    
    # Ensure the uploads directory exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        
    # Ensure the audio directory exists
    if not os.path.exists(AUDIO_FOLDER):
        os.makedirs(AUDIO_FOLDER)
    
    # Ensure the HLS cache directory exists
    if not os.path.exists(HLS_FOLDER):
        os.makedirs(HLS_FOLDER)