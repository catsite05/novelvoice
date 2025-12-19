from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from models import db
from config import Config
import os

# Get the directory of the current file (app.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
root_dir = os.path.dirname(current_dir)
# Specify the template directory relative to the project root
template_dir = os.path.join(root_dir, 'templates')
static_dir = os.path.join(root_dir, 'static')  # In case you have static files

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config.from_object(Config)

db.init_app(app)

# Initialize routes directly in app.py to avoid circular imports
@app.route('/')
def home():
    from flask import render_template
    return render_template('index.html')

@app.route('/novels/list')
def novels_list():
    from flask import render_template
    return render_template('novels.html')

@app.route('/player')
def player():
    from flask import render_template
    return render_template('player.html')

@app.route('/reader')
def reader():
    from flask import render_template
    return render_template('reader.html')

@app.route('/toc')
def toc():
    from flask import render_template
    return render_template('toc.html')

@app.route('/upload', methods=['POST'])
def upload():
    from upload import upload_file
    return upload_file(app)

@app.route('/novels')
def novels():
    from chapter import list_novels
    return jsonify(list_novels())

@app.route('/chapters')
def chapters():
    from flask import request
    from chapter import list_chapters
    
    # Parse novel_id parameter with better error handling
    novel_id_str = request.args.get('novel_id')
    
    # Check if novel_id is missing, null, or 'null' string
    if not novel_id_str or novel_id_str.lower() == 'null':
        novel_id = None
    else:
        try:
            novel_id = int(novel_id_str)
        except (ValueError, TypeError):
            novel_id = None
    
    return jsonify(list_chapters(novel_id))

@app.route('/play/<int:chapter_id>')
def play(chapter_id):
    from audio import play_chapter
    return play_chapter(app, chapter_id)

@app.route('/stream/<int:chapter_id>')
def stream(chapter_id):
    from audio import stream_chapter
    return stream_chapter(app, chapter_id)

@app.route('/novels/delete/<int:novel_id>', methods=['DELETE'])
def delete_novel_route(novel_id):
    from flask import jsonify
    from chapter import delete_novel
    try:
        delete_novel(novel_id)
        return jsonify({"success": True, "message": "小说删除成功"})
    except Exception as e:
        return jsonify({"success": False, "message": f"删除失败: {str(e)}"}), 500

@app.route('/chapter-content')
def chapter_content():
    from flask import request, jsonify
    from chapter import get_chapter_content
    import traceback
    # Debug: Print received parameters
    print(f"Received parameters: novel_id={request.args.get('novel_id')}, chapter_id={request.args.get('chapter_id')}")
    
    # Parse parameters with better error handling
    try:
        novel_id_str = request.args.get('novel_id')
        chapter_id_str = request.args.get('chapter_id')
        
        # Check if parameters are missing or null
        if not novel_id_str or novel_id_str.lower() == 'null' or not chapter_id_str or chapter_id_str.lower() == 'null':
            return jsonify({"error": "Missing or invalid novel_id or chapter_id parameters"}), 400
        
        # Convert to integers
        novel_id = int(novel_id_str)
        chapter_id = int(chapter_id_str)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid parameter values. Expected integers. novel_id={request.args.get('novel_id')}, chapter_id={request.args.get('chapter_id')}"}), 400
    
    print(f"Parsed parameters: novel_id={novel_id}, chapter_id={chapter_id}")
    
    try:
        print(f"Calling get_chapter_content with novel_id={novel_id}, chapter_id={chapter_id}")
        content = get_chapter_content(novel_id, chapter_id)
        print(f"get_chapter_content returned: {content is not None}")
        
        if content is None:
            return jsonify({"error": "Chapter not found"}), 404
        
        return jsonify(content)
    except Exception as e:
        # Log the error for debugging
        print(f"Error getting chapter content: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to get chapter content: {str(e)}"}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)