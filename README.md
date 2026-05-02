#✦ Nexus — Social Networking Platform

A full-featured social networking web app built with **Flask + Python + MySQL**, featuring a stunning dark glassmorphism design and robust comment moderation.

---

## 🚀 Features

- **User Auth** — Register, login, logout with hashed passwords
- **Posts** — Create text/image posts, delete your own posts
- **Comments** — Add comments with **automatic moderation**
- **Likes** — Like/unlike posts (AJAX, no page reload)
- **Follow System** — Follow/unfollow users, follower counts
- **Profiles** — User profiles with bio, avatar upload, post history
- **Search** — Search users and posts
- **Admin Panel** — Full moderation dashboard:
  - View flagged/pending comments
  - Approve or delete flagged comments
  - Manually flag any comment
  - Ban/unban users
  - User management table

---

## 🛡️ ML-Powered 4-Level Comment Moderation

Comments are classified by a **TF-IDF + Logistic Regression** model trained on the [Jigsaw Toxic Comment Classification dataset](https://huggingface.co/datasets/google/jigsaw_toxicity_pred) (Google/Jigsaw, CC0).

| Level | Name | Action | Description |
|---|---|---|---|
| **0** | `CLEAN` | ✅ Auto-approved | Published immediately, no warning |
| **1** | `MILD` | ⚠️ Approved + warned | Published but user receives soft warning |
| **2** | `TOXIC` | 🔶 Held for review | Held in admin queue — not visible until approved |
| **3** | `SEVERE` | 🚫 Auto-blocked | Never inserted to DB, user sees hard error |

### How the 6 Jigsaw labels map to 4 levels
```
severe_toxic / threat / identity_hate  →  Level 3 SEVERE
obscene / insult                        →  Level 2 TOXIC
toxic (only)                            →  Level 1 MILD
none of the above                       →  Level 0 CLEAN
```

### Training the model (required before first run)
```bash
cd socialnet
jupyter notebook comment_moderation_model.ipynb
# Run all cells — takes ~5 min
# Saves: model/moderation_model.pkl + model/tfidf_vectorizer.pkl
```

Until `model/` is present, the app uses a **rule-based fallback** automatically.

---

## 🗄️ Setup Instructions

### 1. Prerequisites
- Python 3.10+
- MySQL 8.0+
- pip

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

> On some systems you may need: `pip install mysqlclient` which requires `libmysqlclient-dev`
> - Ubuntu/Debian: `sudo apt install libmysqlclient-dev`
> - macOS: `brew install mysql-client`

### 3. Create the database
```bash
mysql -u root -p < schema.sql
```

### 4. Configure the app
Edit `app.py` and update these lines:
```python
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'your_password'   # ← change this
app.config['MYSQL_DB'] = 'socialnet'
app.secret_key = 'your-secret-key-change-in-production'  # ← change this
```

### 5. Create admin user
Run this in your MySQL shell (replace the password hash with a real one):
```python
# Generate a hash in Python first:
from werkzeug.security import generate_password_hash
print(generate_password_hash('admin123'))
```
Then update `schema.sql` or insert directly:
```sql
USE socialnet;
INSERT INTO users (username, email, password_hash, bio, is_admin, created_at)
VALUES ('admin', 'admin@example.com', '<paste_hash_here>', 'Site admin', 1, NOW());
```

### 6. Run the app
```bash
python app.py
```

Visit: **http://127.0.0.1:5000**

---

## 📁 Project Structure

```
socialnet/
├── app.py                    # Main Flask app + all routes
├── schema.sql                # MySQL database schema
├── requirements.txt          # Python dependencies
├── README.md
├── static/
│   └── img/
│       └── uploads/          # User uploaded images (auto-created)
└── templates/
    ├── base.html             # Base layout with nav, alerts
    ├── landing.html          # Public landing page
    ├── login.html
    ├── register.html
    ├── feed.html             # Main post feed
    ├── post.html             # Post detail + comments
    ├── new_post.html         # Create post form
    ├── profile.html          # User profile page
    ├── edit_profile.html     # Edit bio + avatar
    ├── search.html           # Search results
    └── admin/
        ├── dashboard.html    # Admin home + flagged comments
        ├── comments.html     # Comment moderation list
        └── users.html        # User management table
```

---

## 🎨 Design System

- **Fonts:** Syne (headings) + DM Sans (body)
- **Theme:** Dark glassmorphism with gradient mesh backgrounds
- **Colors:** Deep space (`#060812`) + violet accent (`#7c6bff`) + pink (`#ff6b9d`) + teal (`#00e5c8`)
- **Components:** Glass cards, gradient buttons, smooth hover transitions

---

## 🔒 Production Notes

Before going live:
1. Set a strong `app.secret_key`
2. Set `debug=False` in `app.run()`
3. Use environment variables for DB credentials
4. Add CSRF protection (`Flask-WTF`)
5. Use a production WSGI server (Gunicorn + Nginx)
6. Configure file upload storage (S3 or similar)
