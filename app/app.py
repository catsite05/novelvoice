from flask import Flask, jsonify, session, redirect, url_for, request, g, render_template
from models import db, User
from config import Config
import os
import threading
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps

# 加载.env文件
try:
    from dotenv import load_dotenv
    # 从项目根目录加载.env文件
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        load_dotenv(env_path)
        print(f"已加载.env文件: {env_path}")
    else:
        print("未找到.env文件，跳过加载")
except ImportError:
    print("警告: python-dotenv未安装，无法加载.env文件")
except Exception as e:
    print(f"加载.env文件时出错: {e}")

# Get the directory of the current file (app.py)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Get the parent directory (project root)
root_dir = os.path.dirname(current_dir)
# Specify the template directory relative to the project root
template_dir = os.path.join(root_dir, 'templates')
static_dir = os.path.join(root_dir, 'static')  # In case you have static files

app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
app.config.from_object(Config)

# Configure ProxyFix for reverse proxy support
# This will handle X-Forwarded-Proto, X-Forwarded-Host, X-Forwarded-For headers
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1, x_prefix=1)

db.init_app(app)


@app.before_request
def load_current_user():
    """在每个请求前加载当前登录用户到 g.current_user"""
    g.current_user = None
    user_id = session.get('user_id')
    if user_id is not None:
        try:
            user = db.session.get(User, user_id)
            if user is None:
                # 用户不存在（可能数据库已重建），清除无效的 session
                session.clear()
            else:
                g.current_user = user
        except Exception:
            # 数据库错误，清除 session
            session.clear()
            g.current_user = None


@app.context_processor
def inject_current_user():
    """在模板中注入 current_user 变量"""
    return {"current_user": getattr(g, 'current_user', None)}


def login_required(view):
    """简单的登录检查装饰器
    - 页面请求未登录时重定向到登录页
    - API/Ajax 请求未登录时返回 401 JSON
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, 'current_user', None) is None:
            # 对于期望 JSON 的请求返回 401
            wants_json = request.is_json or 'application/json' in request.headers.get('Accept', '')
            if wants_json or request.path.startswith((
                '/upload', '/novels', '/chapters', '/stream', '/play'
            )):
                return jsonify({"error": "未登录或登录已过期"}), 401
            # 其他情况重定向到登录页
            # 构建完整的回跳URL，确保包含端口号
            next_url = request.url
            # 如果URL中缺少端口号但请求头中有，则手动添加
            if ':' not in request.host and request.environ.get('HTTP_X_FORWARDED_PORT'):
                port = request.environ.get('HTTP_X_FORWARDED_PORT')
                proto = request.environ.get('HTTP_X_FORWARDED_PROTO', 'https')
                host = request.host
                path = request.full_path.rstrip('?')
                next_url = f"{proto}://{host}:{port}{path}"
            return redirect(url_for('login', next=next_url))
        return view(*args, **kwargs)
    return wrapped


@app.route('/login', methods=['GET', 'POST'])
def login():
    """用户登录"""
    if g.get('current_user') is not None:
        # 已登录则直接跳转
        next_url = request.args.get('next') or url_for('novels_list')
        return redirect(next_url)

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            error = '用户名和密码不能为空'
        else:
            user = User.query.filter_by(username=username).first()
            if user and check_password_hash(user.password_hash, password):
                # 登录成功，写入 session
                session.clear()
                session['user_id'] = user.id
                session.permanent = True  # 使用 PERMANENT_SESSION_LIFETIME 控制过期时间

                next_url = request.args.get('next') or url_for('novels_list')
                return redirect(next_url)
            else:
                error = '用户名或密码错误'

    return render_template('login.html', error=error)


@app.route('/logout')
@login_required
def logout():
    """退出登录"""
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    """超级用户管理和创建其他用户（不支持自助注册）"""
    from flask import abort

    if not g.current_user.is_superuser:
        abort(403)

    message = None
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        is_superuser = bool(request.form.get('is_superuser'))

        if not username or not password:
            error = '用户名和密码不能为空'
        elif User.query.filter_by(username=username).first():
            error = '用户名已存在'
        else:
            new_user = User(
                username=username,
                password_hash=generate_password_hash(password),
                is_superuser=is_superuser,
            )
            db.session.add(new_user)
            db.session.commit()
            message = '用户创建成功'

    users = User.query.order_by(User.id).all()
    return render_template('admin_users.html', users=users, message=message, error=error)


# Initialize routes directly in app.py to avoid circular imports
@app.route('/')
@login_required
def home():
    from flask import render_template
    return render_template('index.html')

@app.route('/novels/list')
@login_required
def novels_list():
    from flask import render_template
    return render_template('novels.html')

@app.route('/player')
@login_required
def player():
    from flask import render_template
    return render_template('player.html')

@app.route('/reader')
@login_required
def reader():
    from flask import render_template
    return render_template('reader.html')

@app.route('/toc')
@login_required
def toc():
    from flask import render_template
    return render_template('toc.html')

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    from upload import upload_file
    return upload_file(app)

@app.route('/novels')
@login_required
def novels():
    from chapter import list_novels
    return jsonify(list_novels())

@app.route('/chapters')
@login_required
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


@app.route('/stream/<int:chapter_id>')
@login_required
def stream(chapter_id):
    from audio import stream_chapter
    return stream_chapter(app, chapter_id)

@app.route('/hls/clear')
@login_required
def hls_clear():
    """清除HLS转换缓存"""
    from hls_manager import get_hls_manager
    hls_manager = get_hls_manager()
    hls_manager.cleanup_chapter_hls()
    return jsonify(success=True)

@app.route('/hls/<int:chapter_id>/stream')
@login_required
def hls_playlist(chapter_id):
    """返回HLS播放列表"""
    from hls_manager import stream_chapter_hls
    
    # 从URL参数表中获取ts参数
    timestamp = float(request.args.get('ts', '0'))
    # print(f"[HLS路由] ts参数: {timestamp}")
    return stream_chapter_hls(app, chapter_id, timestamp)

@app.route('/hls/<int:chapter_id>/<path:filename>')
@login_required
def hls_segments(chapter_id, filename):
    """返回HLS分段文件"""
    from flask import send_from_directory, abort
    from models import Novel, Chapter
    from hls_manager import get_hls_manager
    
    chapter = Chapter.query.get_or_404(chapter_id)
    novel = Novel.query.get_or_404(chapter.novel_id)
    
    # 权限校验
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        abort(403)
    
    # 安全检查: 只允许.ts和.m3u8文件
    if not (filename.endswith('.ts') or filename.endswith('.m3u8')):
        abort(403, "不允许的文件类型")
    
    hls_manager = get_hls_manager()
    hls_dir = hls_manager.get_hls_dir(g.current_user.id)
    
    # 返回分段文件
    response = send_from_directory(
        hls_dir,
        filename,
        mimetype='video/mp2t' if filename.endswith('.ts') else 'application/vnd.apple.mpegurl'
    )
    response.headers['Cache-Control'] = 'public, max-age=86400'  # 分段文件可以长时间缓存
    return response

@app.route('/novels/<int:novel_id>', methods=['DELETE'])
@login_required
def delete_novel_route(novel_id):
    from flask import jsonify
    from chapter import delete_novel
    try:
        delete_novel(novel_id)
        return jsonify({"success": True, "message": "小说删除成功"})
    except Exception as e:
        return jsonify({"success": False, "message": f"删除失败: {str(e)}"}), 500

@app.route('/chapters/<int:chapter_id>', methods=['DELETE'])
@login_required
def delete_chapter_route(chapter_id):
    from flask import jsonify
    from chapter import delete_chapter
    try:
        delete_chapter(chapter_id)
        return jsonify({"success": True, "message": "章节删除成功"})
    except Exception as e:
        return jsonify({"success": False, "message": f"删除失败: {str(e)}"}), 500

@app.route('/chapters/<int:chapter_id>/content')
@login_required
def chapter_content(chapter_id):
    from flask import request, jsonify
    from chapter import get_chapter_content
    import traceback
    
    novel_id_str = request.args.get('novel_id')
    
    if not novel_id_str or novel_id_str.lower() == 'null':
        return jsonify({"error": "Missing or invalid novel_id parameter"}), 400
    
    try:
        novel_id = int(novel_id_str)
    except (ValueError, TypeError) as e:
        return jsonify({"error": f"Invalid parameter values. Expected integers. novel_id={novel_id_str}"}), 400
    
    try:
        content = get_chapter_content(novel_id, chapter_id)
        
        if content is None:
            return jsonify({"error": "Chapter not found"}), 404
        
        return jsonify(content)
    except Exception as e:
        print(f"Error getting chapter content: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": f"Failed to get chapter content: {str(e)}"}), 500

@app.route('/chapters/<int:chapter_id>/script-status')
@login_required
def chapter_script_status(chapter_id):
    from flask import request, jsonify
    from audio_generator import is_chapter_script_ready

    ready = is_chapter_script_ready(chapter_id)
    return jsonify({"ready": ready})


@app.route('/chapters/<int:chapter_id>/script', methods=['POST'])
@login_required
def preprocess_chapter_script_route(chapter_id):
    from flask import request, jsonify
    from audio_generator import preprocess_chapter_script

    def worker(ch_id):
        with app.app_context():
            preprocess_chapter_script(ch_id)

    thread = threading.Thread(target=worker, args=(chapter_id,), daemon=True)
    thread.start()

    return jsonify({"started": True})


@app.route('/chapters/<int:chapter_id>/generation', methods=['DELETE'])
@login_required
def cancel_generation(chapter_id):
    from flask import jsonify
    from audio_generator import cancel_chapter_generation

    cancelled = cancel_chapter_generation(g.current_user.id, chapter_id)
    return jsonify({"cancelled": bool(cancelled)})


@app.route('/novels/<int:novel_id>/reading-progress', methods=['PUT'])
@login_required
def update_reading_progress(novel_id):
    from datetime import datetime, timezone
    from models import Novel
    
    data = request.get_json(silent=True) or {}
    chapter_id = data.get('chapter_id')
    
    if not chapter_id:
        return jsonify({"error": "Missing chapter_id"}), 400
    
    try:
        chapter_id = int(chapter_id)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid parameter values"}), 400
    
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    novel.last_read_chapter_id = chapter_id
    db.session.commit()
    
    return jsonify({"success": True})


@app.route('/novels/<int:novel_id>/reading-progress', methods=['GET'])
@login_required
def get_reading_progress(novel_id):
    from flask import jsonify
    from models import Novel, Chapter
    
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    if novel.last_read_chapter_id:
        return jsonify({
            "chapter_id": novel.last_read_chapter_id,
            "has_progress": True
        })
    
    first_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.start_position).first()
    if first_chapter:
        return jsonify({
            "chapter_id": first_chapter.id,
            "has_progress": False
        })
    
    return jsonify({"error": "该小说暂无章节"}), 404


@app.route('/novels/<int:novel_id>/llm-config', methods=['GET'])
@login_required
def get_novel_llm_config(novel_id):
    """获取小说的LLM配置参数"""
    from flask import jsonify
    from models import Novel
    
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    return jsonify({
        "llm_api_key": novel.llm_api_key or '',
        "llm_base_url": novel.llm_base_url or '',
        "llm_model": novel.llm_model or ''
    })


@app.route('/novels/<int:novel_id>/audio-progress', methods=['PUT'])
@login_required
def update_audio_progress(novel_id):
    """更新音频播放进度（包含章节内的播放位置）"""
    from datetime import datetime, timezone
    from models import AudioProgress, Novel
    
    data = request.get_json(silent=True) or {}
    chapter_id = data.get('chapter_id')
    position = data.get('position', 0.0)
    
    if not chapter_id:
        return jsonify({"error": "Missing chapter_id"}), 400
    
    try:
        chapter_id = int(chapter_id)
        position = float(position)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid parameter values"}), 400
    
    # 获取小说并检查权限
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    # 查找或创建播放进度记录
    progress = AudioProgress.query.filter_by(
        user_id=g.current_user.id,
        novel_id=novel_id
    ).first()
    
    if progress:
        # 更新现有记录
        progress.chapter_id = chapter_id
        progress.position = position
        progress.updated_at = datetime.now(timezone.utc)
    else:
        # 创建新记录
        progress = AudioProgress(
            user_id=g.current_user.id,
            novel_id=novel_id,
            chapter_id=chapter_id,
            position=position,
            updated_at=datetime.now(timezone.utc)
        )
        db.session.add(progress)
    
    db.session.commit()
    
    return jsonify({"success": True})


@app.route('/novels/<int:novel_id>/audio-progress', methods=['GET'])
@login_required
def get_audio_progress(novel_id):
    """获取音频播放进度"""
    from models import Novel, Chapter, AudioProgress
    
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    # 查找播放进度记录
    progress = AudioProgress.query.filter_by(
        user_id=g.current_user.id,
        novel_id=novel_id
    ).first()
    
    if progress:
        chapter = db.session.get(Chapter, progress.chapter_id)
        if chapter:
            return jsonify({
                "chapter_id": progress.chapter_id,
                "position": progress.position,
                "has_progress": True
            })
        else:
            # 章节已被删除，返回第一章
            first_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.start_position).first()
            if first_chapter:
                return jsonify({
                    "chapter_id": first_chapter.id,
                    "position": 0.0,
                    "has_progress": False
                })
    
    # 没有播放进度，返回第一章
    first_chapter = Chapter.query.filter_by(novel_id=novel_id).order_by(Chapter.start_position).first()
    if first_chapter:
        return jsonify({
            "chapter_id": first_chapter.id,
            "position": 0.0,
            "has_progress": False
        })
    
    return jsonify({"error": "该小说暂无章节"}), 404


@app.route('/novels/<int:novel_id>/llm-config', methods=['POST'])
@login_required
def update_novel_llm_config(novel_id):
    """更新小说的LLM配置参数"""
    from flask import request, jsonify
    from models import Novel
    
    novel = Novel.query.get_or_404(novel_id)
    if not g.current_user.is_superuser and novel.user_id != g.current_user.id:
        return jsonify({"error": "无权限"}), 403
    
    data = request.get_json(silent=True) or {}
    
    # 更新LLM配置，如果为空字符串则设为None
    novel.llm_api_key = data.get('llm_api_key', '').strip() or None
    novel.llm_base_url = data.get('llm_base_url', '').strip() or None
    novel.llm_model = data.get('llm_model', '').strip() or None
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "LLM配置更新成功"})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5002, debug=True)