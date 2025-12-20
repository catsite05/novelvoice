import os

# Get the directory of the config file (app/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
root_dir = os.path.dirname(current_dir)

class Config:
    # Database configuration
    SQLALCHEMY_DATABASE_URI = 'sqlite:///novelvoice.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload folder configuration (使用绝对路径)
    UPLOAD_FOLDER = os.path.join(root_dir, 'uploads')
    AUDIO_FOLDER = os.path.join(root_dir, 'audio')
    
    # Ensure the uploads directory exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        
    # Ensure the audio directory exists
    if not os.path.exists(AUDIO_FOLDER):
        os.makedirs(AUDIO_FOLDER)