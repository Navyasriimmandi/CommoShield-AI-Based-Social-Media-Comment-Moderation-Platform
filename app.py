from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
import os
import datetime
import re
from moderator import predict as moderate_predict, LEVELS as MODERATION_LEVELS

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-in-production'

# MySQL Configuration
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = ''
app.config['MYSQL_DB'] = 'socialnet'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

# Upload config
app.config['UPLOAD_FOLDER'] = 'static/img/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

mysql = MySQL(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        cur = mysql.connection.cursor()
        cur.execute("SELECT is_admin FROM users WHERE id = %s", (session['user_id'],))
        user = cur.fetchone()
        cur.close()
        if not user or not user['is_admin']:
            flash('Admin access required.', 'error')
            return redirect(url_for('feed'))
        return f(*args, **kwargs)
    return decorated

# ============ ROUTES ============

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('feed'))
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password']
        bio = request.form.get('bio', '').strip()

        if not username or not email or not password:
            flash('All fields required.', 'error')
            return render_template('register.html')

        cur = mysql.connection.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s OR email=%s", (username, email))
        if cur.fetchone():
            flash('Username or email already taken.', 'error')
            cur.close()
            return render_template('register.html')

        hashed = generate_password_hash(password)
        cur.execute("INSERT INTO users (username, email, password_hash, bio, created_at) VALUES (%s,%s,%s,%s,%s)",
                    (username, email, hashed, bio, datetime.datetime.now()))
        mysql.connection.commit()
        cur.close()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier'].strip()
        password = request.form['password']
        cur = mysql.connection.cursor()
        cur.execute("SELECT * FROM users WHERE username=%s OR email=%s", (identifier, identifier))
        user = cur.fetchone()
        cur.close()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            return redirect(url_for('feed'))
        flash('Invalid credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/feed')
@login_required
def feed():
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT p.*, u.username, u.avatar,
               (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
               (SELECT COUNT(*) FROM comments WHERE post_id=p.id AND status='approved') as comment_count,
               (SELECT id FROM likes WHERE post_id=p.id AND user_id=%s) as user_liked
        FROM posts p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC LIMIT 50
    """, (session['user_id'],))
    posts = cur.fetchall()
    cur.close()
    return render_template('feed.html', posts=posts)

@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if request.method == 'POST':
        content = request.form['content'].strip()
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"{ts}_{filename}"
                os.makedirs(os.path.join(app.root_path, app.config['UPLOAD_FOLDER']), exist_ok=True)
                file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                image_url = f"img/uploads/{filename}"
        if not content:
            flash('Post content required.', 'error')
            return render_template('new_post.html')
        cur = mysql.connection.cursor()
        cur.execute("INSERT INTO posts (user_id, content, image_url, created_at) VALUES (%s,%s,%s,%s)",
                    (session['user_id'], content, image_url, datetime.datetime.now()))
        mysql.connection.commit()
        cur.close()
        flash('Post shared!', 'success')
        return redirect(url_for('feed'))
    return render_template('new_post.html')

@app.route('/post/<int:post_id>')
@login_required
def view_post(post_id):
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT p.*, u.username, u.avatar,
               (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
               (SELECT id FROM likes WHERE post_id=p.id AND user_id=%s) as user_liked
        FROM posts p JOIN users u ON p.user_id=u.id WHERE p.id=%s
    """, (session['user_id'], post_id))
    post = cur.fetchone()
    if not post:
        flash('Post not found.', 'error')
        return redirect(url_for('feed'))
    cur.execute("""
        SELECT c.*, u.username, u.avatar FROM comments c
        JOIN users u ON c.user_id=u.id
        WHERE c.post_id=%s AND c.status='approved'
        ORDER BY c.created_at ASC
    """, (post_id,))
    comments = cur.fetchall()
    cur.close()
    return render_template('post.html', post=post, comments=comments)

@app.route('/post/<int:post_id>/comment', methods=['POST'])
@login_required
def add_comment(post_id):
    text = request.form['content'].strip()
    if not text:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('view_post', post_id=post_id))

    # ── ML-powered 4-level moderation ────────────────────────
    result = moderate_predict(text)
    level      = result['level']        # 0-3
    status     = result['status']       # approved / flagged / blocked
    flag_reason = result['flag_reason']
    user_msg   = result['user_msg']
    icon       = result['icon']
    level_name = result['level_name']

    # Level 3 SEVERE → blocked, never inserted
    if level == 3:
        flash(f'{icon} {user_msg}', 'error')
        return redirect(url_for('view_post', post_id=post_id))

    cur = mysql.connection.cursor()
    cur.execute("""INSERT INTO comments (post_id, user_id, content, status, flag_reason,
                   moderation_level, moderation_confidence, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (post_id, session['user_id'], text, status, flag_reason,
                 level, result['confidence'], datetime.datetime.now()))
    mysql.connection.commit()
    cur.close()

    if level == 0:
        flash('Comment posted! ✅', 'success')
    elif level == 1:
        flash(f'{icon} Comment posted. {user_msg}', 'warning')
    else:  # level 2
        flash(f'{icon} {user_msg}', 'warning')

    return redirect(url_for('view_post', post_id=post_id))

@app.route('/post/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM likes WHERE post_id=%s AND user_id=%s", (post_id, session['user_id']))
    existing = cur.fetchone()
    if existing:
        cur.execute("DELETE FROM likes WHERE post_id=%s AND user_id=%s", (post_id, session['user_id']))
        liked = False
    else:
        cur.execute("INSERT INTO likes (post_id, user_id) VALUES (%s,%s)", (post_id, session['user_id']))
        liked = True
    mysql.connection.commit()
    cur.execute("SELECT COUNT(*) as cnt FROM likes WHERE post_id=%s", (post_id,))
    count = cur.fetchone()['cnt']
    cur.close()
    return jsonify({'liked': liked, 'count': count})

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT user_id FROM posts WHERE id=%s", (post_id,))
    post = cur.fetchone()
    if post and (post['user_id'] == session['user_id'] or session.get('is_admin')):
        cur.execute("DELETE FROM comments WHERE post_id=%s", (post_id,))
        cur.execute("DELETE FROM likes WHERE post_id=%s", (post_id,))
        cur.execute("DELETE FROM posts WHERE id=%s", (post_id,))
        mysql.connection.commit()
        flash('Post deleted.', 'success')
    cur.close()
    return redirect(url_for('feed'))

@app.route('/profile/<username>')
@login_required
def profile(username):
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('feed'))
    cur.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
               (SELECT COUNT(*) FROM comments WHERE post_id=p.id AND status='approved') as comment_count
        FROM posts p WHERE p.user_id=%s ORDER BY p.created_at DESC
    """, (user['id'],))
    posts = cur.fetchall()

    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE follower_id=%s AND following_id=%s",
                (session['user_id'], user['id']))
    is_following = cur.fetchone()['cnt'] > 0
    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE following_id=%s", (user['id'],))
    followers = cur.fetchone()['cnt']
    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE follower_id=%s", (user['id'],))
    following = cur.fetchone()['cnt']
    cur.close()
    return render_template('profile.html', user=user, posts=posts,
                           is_following=is_following, followers=followers, following=following)

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow(user_id):
    if user_id == session['user_id']:
        return jsonify({'error': 'Cannot follow yourself'}), 400
    cur = mysql.connection.cursor()
    cur.execute("SELECT id FROM follows WHERE follower_id=%s AND following_id=%s",
                (session['user_id'], user_id))
    if cur.fetchone():
        cur.execute("DELETE FROM follows WHERE follower_id=%s AND following_id=%s",
                    (session['user_id'], user_id))
        following = False
    else:
        cur.execute("INSERT INTO follows (follower_id, following_id) VALUES (%s,%s)",
                    (session['user_id'], user_id))
        following = True
    mysql.connection.commit()
    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE following_id=%s", (user_id,))
    count = cur.fetchone()['cnt']
    cur.close()
    return jsonify({'following': following, 'count': count})

@app.route('/profile/<username>/edit', methods=['GET', 'POST'])
@login_required
def edit_profile(username):
    if session['username'] != username:
        return redirect(url_for('profile', username=session['username']))
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM users WHERE username=%s", (username,))
    user = cur.fetchone()
    if request.method == 'POST':
        bio = request.form.get('bio', '').strip()
        avatar = user['avatar']
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ts = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"avatar_{ts}_{filename}"
                os.makedirs(os.path.join(app.root_path, app.config['UPLOAD_FOLDER']), exist_ok=True)
                file.save(os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename))
                avatar = f"img/uploads/{filename}"
        cur.execute("UPDATE users SET bio=%s, avatar=%s WHERE id=%s", (bio, avatar, session['user_id']))
        mysql.connection.commit()
        flash('Profile updated!', 'success')
        cur.close()
        return redirect(url_for('profile', username=username))
    cur.close()
    return render_template('edit_profile.html', user=user)

@app.route('/search')
@login_required
def search():
    q = request.args.get('q', '').strip()
    users, posts = [], []
    if q:
        cur = mysql.connection.cursor()
        cur.execute("SELECT id, username, avatar, bio FROM users WHERE username LIKE %s LIMIT 10",
                    (f'%{q}%',))
        users = cur.fetchall()
        cur.execute("""SELECT p.*, u.username, u.avatar FROM posts p JOIN users u ON p.user_id=u.id
                       WHERE p.content LIKE %s ORDER BY p.created_at DESC LIMIT 20""", (f'%{q}%',))
        posts = cur.fetchall()
        cur.close()
    return render_template('search.html', users=users, posts=posts, query=q)

# ============ USER DASHBOARD ============

@app.route('/dashboard')
@login_required
def user_dashboard():
    uid = session['user_id']
    cur = mysql.connection.cursor()

    # ── Core stats ──────────────────────────────────────────
    cur.execute("SELECT COUNT(*) as cnt FROM posts WHERE user_id=%s", (uid,))
    total_posts = cur.fetchone()['cnt']

    cur.execute("""SELECT COUNT(*) as cnt FROM comments WHERE user_id=%s""", (uid,))
    total_comments = cur.fetchone()['cnt']

    cur.execute("""SELECT COUNT(*) as cnt FROM likes l
                   JOIN posts p ON l.post_id=p.id WHERE p.user_id=%s""", (uid,))
    total_likes_received = cur.fetchone()['cnt']

    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE following_id=%s", (uid,))
    followers_count = cur.fetchone()['cnt']

    cur.execute("SELECT COUNT(*) as cnt FROM follows WHERE follower_id=%s", (uid,))
    following_count = cur.fetchone()['cnt']

    # ── Comment moderation breakdown (MY comments) ─────────
    cur.execute("""SELECT moderation_level, status, COUNT(*) as cnt
                   FROM comments WHERE user_id=%s
                   GROUP BY moderation_level, status""", (uid,))
    mod_rows = cur.fetchall()
    my_level_counts = {0:0, 1:0, 2:0, 3:0}
    my_flagged_count = 0
    for row in mod_rows:
        lvl = row['moderation_level']
        if lvl is not None:
            my_level_counts[lvl] = my_level_counts.get(lvl, 0) + row['cnt']
        if row['status'] == 'flagged':
            my_flagged_count += row['cnt']

    # ── My recent posts with engagement ─────────────────────
    cur.execute("""
        SELECT p.*,
               (SELECT COUNT(*) FROM likes WHERE post_id=p.id) as like_count,
               (SELECT COUNT(*) FROM comments WHERE post_id=p.id AND status='approved') as comment_count
        FROM posts p WHERE p.user_id=%s
        ORDER BY p.created_at DESC LIMIT 5
    """, (uid,))
    recent_posts = cur.fetchall()

    # ── My recent comments with their moderation status ─────
    cur.execute("""
        SELECT c.*, p.content as post_preview, p.id as post_id,
               pu.username as post_author
        FROM comments c
        JOIN posts p ON c.post_id=p.id
        JOIN users pu ON p.user_id=pu.id
        WHERE c.user_id=%s
        ORDER BY c.created_at DESC LIMIT 10
    """, (uid,))
    my_comments = cur.fetchall()

    # ── Replies TO my posts (comments on my posts by others) ─
    cur.execute("""
        SELECT c.*, u.username as commenter, u.avatar as commenter_avatar,
               p.content as post_preview, p.id as post_id
        FROM comments c
        JOIN users u ON c.user_id=u.id
        JOIN posts p ON c.post_id=p.id
        WHERE p.user_id=%s AND c.user_id != %s AND c.status='approved'
        ORDER BY c.created_at DESC LIMIT 10
    """, (uid, uid))
    replies_to_me = cur.fetchall()

    # ── Who liked my posts recently ─────────────────────────
    cur.execute("""
        SELECT l.*, u.username as liker, u.avatar as liker_avatar,
               p.content as post_preview, p.id as post_id
        FROM likes l
        JOIN users u ON l.user_id=u.id
        JOIN posts p ON l.post_id=p.id
        WHERE p.user_id=%s AND l.user_id != %s
        ORDER BY l.id DESC LIMIT 10
    """, (uid, uid))
    recent_likes = cur.fetchall()

    # ── New followers ────────────────────────────────────────
    cur.execute("""
        SELECT f.*, u.username, u.avatar, u.bio
        FROM follows f JOIN users u ON f.follower_id=u.id
        WHERE f.following_id=%s
        ORDER BY f.created_at DESC LIMIT 8
    """, (uid,))
    new_followers = cur.fetchall()

    # ── Top post (most liked) ────────────────────────────────
    cur.execute("""
        SELECT p.*, COUNT(l.id) as like_count,
               (SELECT COUNT(*) FROM comments WHERE post_id=p.id AND status='approved') as comment_count
        FROM posts p LEFT JOIN likes l ON p.id=l.post_id
        WHERE p.user_id=%s GROUP BY p.id
        ORDER BY like_count DESC LIMIT 1
    """, (uid,))
    top_post = cur.fetchone()

    # ── Activity feed: merged likes + replies sorted by recency ─
    activity = []
    for r in replies_to_me:
        activity.append({
            'type': 'comment', 'user': r['commenter'],
            'avatar': r['commenter_avatar'],
            'text': f'commented on your post',
            'detail': r['content'][:80],
            'post_id': r['post_id'],
            'time': r['created_at'],
        })
    for lk in recent_likes:
        activity.append({
            'type': 'like', 'user': lk['liker'],
            'avatar': lk['liker_avatar'],
            'text': 'liked your post',
            'detail': lk['post_preview'][:80],
            'post_id': lk['post_id'],
            'time': None,
        })
    for nf in new_followers:
        activity.append({
            'type': 'follow', 'user': nf['username'],
            'avatar': nf['avatar'],
            'text': 'started following you',
            'detail': nf['bio'][:60] if nf['bio'] else '',
            'post_id': None,
            'time': nf.get('created_at'),
        })
    # sort by time descending (None last)
    activity.sort(key=lambda x: x['time'] or datetime.datetime(2000,1,1), reverse=True)
    activity = activity[:20]

    cur.close()
    return render_template('user_dashboard.html',
        total_posts=total_posts,
        total_comments=total_comments,
        total_likes_received=total_likes_received,
        followers_count=followers_count,
        following_count=following_count,
        my_level_counts=my_level_counts,
        my_flagged_count=my_flagged_count,
        recent_posts=recent_posts,
        my_comments=my_comments,
        replies_to_me=replies_to_me,
        recent_likes=recent_likes,
        new_followers=new_followers,
        top_post=top_post,
        activity=activity,
    )

# ============ ADMIN ROUTES ============

@app.route('/admin')
@admin_required
def admin_dashboard():
    cur = mysql.connection.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users")
    total_users = cur.fetchone()['cnt']
    cur.execute("SELECT COUNT(*) as cnt FROM posts")
    total_posts = cur.fetchone()['cnt']
    cur.execute("SELECT COUNT(*) as cnt FROM comments WHERE status='flagged'")
    pending_comments = cur.fetchone()['cnt']
    cur.execute("SELECT COUNT(*) as cnt FROM comments")
    total_comments = cur.fetchone()['cnt']
    # Level breakdown
    cur.execute("""SELECT moderation_level, COUNT(*) as cnt FROM comments
                   GROUP BY moderation_level ORDER BY moderation_level""")
    level_counts_raw = cur.fetchall()
    level_counts = {0:0, 1:0, 2:0, 3:0}
    for row in level_counts_raw:
        if row['moderation_level'] is not None:
            level_counts[row['moderation_level']] = row['cnt']
    cur.execute("""SELECT c.*, u.username, p.content as post_preview
                   FROM comments c JOIN users u ON c.user_id=u.id
                   JOIN posts p ON c.post_id=p.id
                   WHERE c.status='flagged' ORDER BY c.created_at DESC LIMIT 20""")
    flagged = cur.fetchall()
    cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 10")
    recent_users = cur.fetchall()
    cur.close()
    return render_template('admin/dashboard.html',
                           total_users=total_users, total_posts=total_posts,
                           pending_comments=pending_comments, total_comments=total_comments,
                           flagged=flagged, recent_users=recent_users,
                           level_counts=level_counts,
                           moderation_levels=MODERATION_LEVELS)

@app.route('/admin/comment/<int:comment_id>/<action>', methods=['POST'])
@admin_required
def moderate_action(comment_id, action):
    cur = mysql.connection.cursor()
    if action == 'approve':
        cur.execute("UPDATE comments SET status='approved', flag_reason=NULL WHERE id=%s", (comment_id,))
        flash('Comment approved.', 'success')
    elif action == 'reject':
        cur.execute("DELETE FROM comments WHERE id=%s", (comment_id,))
        flash('Comment deleted.', 'success')
    elif action == 'flag':
        reason = request.form.get('reason', 'Manually flagged by admin')
        cur.execute("UPDATE comments SET status='flagged', flag_reason=%s WHERE id=%s", (reason, comment_id))
        flash('Comment flagged.', 'warning')
    mysql.connection.commit()
    cur.close()
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/users')
@admin_required
def admin_users():
    cur = mysql.connection.cursor()
    cur.execute("""SELECT u.*, COUNT(p.id) as post_count FROM users u
                   LEFT JOIN posts p ON u.id=p.user_id GROUP BY u.id ORDER BY u.created_at DESC""")
    users = cur.fetchall()
    cur.close()
    return render_template('admin/users.html', users=users)

@app.route('/admin/user/<int:user_id>/toggle-ban', methods=['POST'])
@admin_required
def toggle_ban(user_id):
    cur = mysql.connection.cursor()
    cur.execute("SELECT is_banned FROM users WHERE id=%s", (user_id,))
    user = cur.fetchone()
    if user:
        new_status = 0 if user['is_banned'] else 1
        cur.execute("UPDATE users SET is_banned=%s WHERE id=%s", (new_status, user_id))
        mysql.connection.commit()
        flash('User status updated.', 'success')
    cur.close()
    return redirect(url_for('admin_users'))

@app.route('/admin/comments')
@admin_required
def admin_comments():
    status_filter = request.args.get('status', 'all')
    cur = mysql.connection.cursor()
    if status_filter == 'all':
        cur.execute("""SELECT c.*, u.username, p.content as post_preview
                       FROM comments c JOIN users u ON c.user_id=u.id JOIN posts p ON c.post_id=p.id
                       ORDER BY c.created_at DESC LIMIT 100""")
    else:
        cur.execute("""SELECT c.*, u.username, p.content as post_preview
                       FROM comments c JOIN users u ON c.user_id=u.id JOIN posts p ON c.post_id=p.id
                       WHERE c.status=%s ORDER BY c.created_at DESC LIMIT 100""", (status_filter,))
    comments = cur.fetchall()
    cur.close()
    return render_template('admin/comments.html', comments=comments, status_filter=status_filter)

if __name__ == '__main__':
    app.run(debug=True)
