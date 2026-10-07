from flask import Flask, render_template_string, request, jsonify
import threading
import time
import random
import string
import os
import json
from datetime import datetime, timedelta
import requests
from werkzeug.utils import secure_filename
import pytz
import re

app = Flask(__name__)
app.secret_key = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

# Configure upload folders
UPLOAD_FOLDER = 'uploads'
TASKS_FOLDER = 'tasks'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(TASKS_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['TASKS_FOLDER'] = TASKS_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Store active tasks
active_tasks = {}
task_status = {}

# Realistic User Agents for v17.0
USER_AGENTS = [
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/120.0',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
]

class CommentBot:
    def __init__(self, task_id, post_id, haters_name, last_name, interval, 
                 comments, tokens, token_type, photo_path=None, uploaded_photo_path=None):
        self.task_id = task_id
        self.post_id = post_id
        self.haters_name = haters_name
        self.last_name = last_name
        self.interval = interval
        self.comments = comments
        self.tokens = tokens
        self.token_type = token_type
        self.photo_path = photo_path
        self.uploaded_photo_path = uploaded_photo_path
        self.running = False
        self.start_time = None
        self.total_comments = 0
        self.error_count = 0
        self.max_errors = 10  # Max consecutive errors before cooling down
        
    def get_random_user_agent(self):
        return random.choice(USER_AGENTS)
    
    def get_headers(self):
        """Get realistic browser headers"""
        return {
            'User-Agent': self.get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'TE': 'trailers'
        }
    
    def post_comment(self, token, comment_text):
        """Post comment to Facebook using v17.0 API with optional photo attachment"""
        full_comment = f"{self.haters_name} {comment_text} {self.last_name}"
        url = f"https://graph.facebook.com/v17.0/{self.post_id}/comments"
        
        params = {
            'message': full_comment,
            'access_token': token,
            'pretty': '0'
        }
        
        # Check photo availability
        target_photo = None
        if self.photo_path and os.path.exists(self.photo_path):
            target_photo = self.photo_path
        elif self.uploaded_photo_path and os.path.exists(self.uploaded_photo_path):
            target_photo = self.uploaded_photo_path

        time.sleep(random.uniform(1, 3))
        
        try:
            headers = self.get_headers()
            
            if target_photo:
                with open(target_photo, 'rb') as img:
                    files = {'source': img}
                    response = requests.post(
                        url, 
                        params=params, 
                        files=files,
                        headers=headers,
                        timeout=30
                    )
            else:
                response = requests.post(
                    url, 
                    params=params, 
                    headers=headers,
                    timeout=30
                )
            
            if response.status_code == 200:
                return True, "Success"
            else:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                return False, error_msg
                
        except requests.exceptions.Timeout:
            return False, "Timeout error"
        except requests.exceptions.ConnectionError:
            return False, "Connection error"
        except Exception as e:
            return False, str(e)
    
    def run_single_token(self):
        """Run with single token - round robin through comments"""
        token = self.tokens[0]
        comment_index = 0
        
        while self.running:
            try:
                current_comment = self.comments[comment_index % len(self.comments)]
                success, message = self.post_comment(token, current_comment)
                
                if success:
                    self.total_comments += 1
                    self.error_count = 0
                    print(f"[{self.task_id}] ✓ Comment {self.total_comments} posted")
                else:
                    self.error_count += 1
                    print(f"[{self.task_id}] ✗ Error: {message}")
                    
                    if self.error_count >= self.max_errors:
                        print(f"[{self.task_id}] ⏳ Too many errors, cooling down for 5 minutes...")
                        time.sleep(300)
                        self.error_count = 0
                
                comment_index += 1
                self.update_status()
                
                if self.running:
                    time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in single token mode: {e}")
                self.error_count += 1
                time.sleep(10)
    
    def run_multi_token(self):
        """Run with multiple tokens - round robin through tokens and comments"""
        token_index = 0
        comment_index = 0
        
        while self.running:
            try:
                current_token = self.tokens[token_index % len(self.tokens)]
                current_comment = self.comments[comment_index % len(self.comments)]
                
                success, message = self.post_comment(current_token, current_comment)
                
                if success:
                    self.total_comments += 1
                    self.error_count = 0
                    print(f"[{self.task_id}] ✓ Comment {self.total_comments} posted with token {token_index+1}")
                else:
                    self.error_count += 1
                    print(f"[{self.task_id}] ✗ Error with token {token_index+1}: {message}")
                    
                    if self.error_count >= self.max_errors:
                        print(f"[{self.task_id}] ⏳ Too many errors, cooling down for 5 minutes...")
                        time.sleep(300)
                        self.error_count = 0
                
                comment_index += 1
                if comment_index % len(self.comments) == 0:
                    token_index += 1
                
                self.update_status()
                
                if self.running:
                    time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in multi token mode: {e}")
                self.error_count += 1
                time.sleep(10)
    
    def update_status(self):
        """Update task status with IST time"""
        if self.start_time:
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist)
            uptime = now - self.start_time
            
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            seconds = uptime.seconds % 60
            
            task_status[self.task_id] = {
                'running': self.running,
                'start_time': self.start_time.strftime('%d %B %Y %I:%M:%S %p'),
                'uptime': f"{days}d {hours}h {minutes}m {seconds}s",
                'total_comments': self.total_comments,
                'post_id': self.post_id,
                'error_count': self.error_count,
                'last_update': now.strftime('%I:%M:%S %p')
            }
    
    def start(self):
        """Start the bot"""
        self.running = True
        ist = pytz.timezone('Asia/Kolkata')
        self.start_time = datetime.now(ist)
        
        print(f"[{self.task_id}] ✅ Task started at {self.start_time}")
        
        if self.token_type == 'single':
            self.run_single_token()
        else:
            self.run_multi_token()
    
    def stop(self):
        """Stop the bot"""
        self.running = False
        self.update_status()
        print(f"[{self.task_id}] ⏹️ Task stopped")

def generate_task_id():
    return ''.join(random.choices(string.digits, k=5))

def validate_post_id(post_id):
    post_id = post_id.strip()
    if post_id and post_id.isdigit():
        return True
    return False

# Luxury Dark Gold HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AYUSH PREMIUM TOOL v17.0</title>
    <link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Rajdhani:wght@500;600;700&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body { 
            font-family: 'Rajdhani', sans-serif; 
            background: #090a0f; 
            background-image: 
                radial-gradient(at 0% 0%, rgba(212, 175, 55, 0.12) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(255, 69, 0, 0.08) 0px, transparent 50%),
                radial-gradient(at 50% 50%, rgba(15, 18, 28, 0.9) 0px, #050608 100%);
            min-height: 100vh; 
            padding: 2rem; 
            color: #e2e8f0; 
        }

        .container { max-width: 1400px; margin: 0 auto; }

        /* Premium Header Styling */
        .header { text-align: center; margin-bottom: 3rem; position: relative; }
        
        .main-brand {
            font-family: 'Orbitron', sans-serif;
            font-size: 3.5rem;
            font-weight: 900;
            letter-spacing: 4px;
            background: linear-gradient(135deg, #FFF 0%, #FFD700 40%, #D4AF37 70%, #B8860B 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 30px rgba(212, 175, 55, 0.3);
            text-transform: uppercase;
            margin-bottom: 0.3rem;
            animation: pulseGlow 3s ease-in-out infinite alternate;
        }

        @keyframes pulseGlow {
            0% { filter: drop-shadow(0 0 10px rgba(212, 175, 55, 0.2)); }
            100% { filter: drop-shadow(0 0 25px rgba(212, 175, 55, 0.6)); }
        }

        .badge { 
            background: linear-gradient(135deg, #D4AF37, #996515); 
            color: #000; 
            padding: 0.4rem 1.4rem; 
            border-radius: 50px; 
            display: inline-block; 
            font-family: 'Orbitron', sans-serif;
            font-weight: 800; 
            font-size: 0.85rem; 
            letter-spacing: 2px; 
            box-shadow: 0 0 15px rgba(212, 175, 55, 0.4); 
            border: 1px solid rgba(255, 255, 255, 0.4);
        }

        .subtitle { font-size: 1.2rem; color: #a0aec0; margin-top: 0.8rem; letter-spacing: 1px; }

        .main-grid { display: grid; grid-template-columns: 2fr 1fr; gap: 2rem; }

        /* Glassmorphism Dark Cards */
        .card { 
            background: rgba(15, 20, 30, 0.75); 
            backdrop-filter: blur(16px); 
            border-radius: 24px; 
            padding: 2.2rem; 
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.8), inset 0 1px 1px rgba(255, 255, 255, 0.1); 
            border: 1px solid rgba(212, 175, 55, 0.25); 
            transition: all 0.4s ease; 
        }

        .card:hover { 
            transform: translateY(-5px); 
            border-color: rgba(212, 175, 55, 0.6);
            box-shadow: 0 25px 60px rgba(212, 175, 55, 0.15); 
        }

        .card h2 { 
            font-family: 'Orbitron', sans-serif;
            font-size: 1.6rem; 
            margin-bottom: 1.5rem; 
            color: #FFD700; 
            border-left: 4px solid #D4AF37; 
            padding-left: 1rem; 
            letter-spacing: 1px;
        }

        .form-group { margin-bottom: 1.5rem; }
        .form-group label { 
            display: block; 
            margin-bottom: 0.5rem; 
            font-weight: 700; 
            color: #cbd5e0; 
            font-size: 0.95rem; 
            text-transform: uppercase; 
            letter-spacing: 1px; 
        }

        .form-control { 
            width: 100%; 
            padding: 1rem 1.2rem; 
            border: 1px solid rgba(212, 175, 55, 0.2); 
            border-radius: 12px; 
            font-size: 1rem; 
            background: rgba(5, 8, 15, 0.8); 
            transition: all 0.3s ease; 
            color: #fff; 
            font-family: 'Rajdhani', sans-serif;
            font-weight: 600;
        }

        .form-control:focus { 
            outline: none; 
            border-color: #FFD700; 
            box-shadow: 0 0 15px rgba(212, 175, 55, 0.3); 
            background: rgba(10, 15, 25, 0.95); 
        }

        textarea.form-control { resize: vertical; min-height: 100px; }

        .token-toggle { display: flex; gap: 1rem; background: rgba(0, 0, 0, 0.5); padding: 0.5rem; border-radius: 50px; border: 1px solid rgba(212, 175, 55, 0.2); }
        .toggle-option { flex: 1; text-align: center; padding: 0.9rem; border-radius: 40px; cursor: pointer; transition: all 0.3s ease; font-weight: 700; color: #a0aec0; }
        input[type="radio"] { display: none; }
        input[type="radio"]:checked + .toggle-option { 
            background: linear-gradient(135deg, #D4AF37, #996515); 
            color: #000; 
            font-weight: 800;
            box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4); 
        }

        .file-upload { 
            margin-top: 1rem; 
            padding: 1.2rem; 
            background: rgba(5, 8, 15, 0.6); 
            border: 2px dashed rgba(212, 175, 55, 0.4); 
            border-radius: 12px; 
            text-align: center; 
            cursor: pointer; 
            transition: all 0.3s ease; 
        }

        .file-upload:hover { 
            background: rgba(212, 175, 55, 0.05); 
            border-color: #FFD700; 
        }

        .file-upload input[type="file"] { display: none; }
        .file-upload label { color: #FFD700; font-weight: 700; cursor: pointer; letter-spacing: 1px;}

        /* Premium Buttons */
        .btn { 
            width: 100%; 
            padding: 1.1rem; 
            border: none; 
            border-radius: 12px; 
            font-family: 'Orbitron', sans-serif;
            font-size: 1.1rem; 
            font-weight: 800; 
            cursor: pointer; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            gap: 1rem; 
            transition: all 0.3s ease; 
            letter-spacing: 2px;
            text-transform: uppercase;
        }

        .btn-start { 
            background: linear-gradient(135deg, #FFD700 0%, #D4AF37 50%, #8B6508 100%); 
            color: #000; 
            box-shadow: 0 5px 20px rgba(212, 175, 55, 0.4); 
        }

        .btn-stop { 
            background: linear-gradient(135deg, #e53e3e 0%, #9b2c2c 100%); 
            color: #fff; 
            box-shadow: 0 5px 20px rgba(229, 62, 62, 0.4); 
        }

        .btn-status { 
            background: linear-gradient(135deg, #3182ce 0%, #2b6cb0 100%); 
            color: #fff; 
            box-shadow: 0 5px 20px rgba(49, 130, 206, 0.4); 
        }

        .btn:hover { transform: translateY(-3px); filter: brightness(1.2); }
        .btn:active { transform: translateY(0); }

        .status-display { margin-top: 2rem; padding: 1.5rem; background: rgba(5, 8, 15, 0.8); border-radius: 16px; border: 1px solid rgba(212, 175, 55, 0.2); }
        .status-display h3 { font-family: 'Orbitron', sans-serif; color: #FFD700; margin-bottom: 1rem; font-size: 1.2rem; }
        .status-item { display: flex; justify-content: space-between; padding: 0.8rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
        .status-label { font-weight: 700; color: #a0aec0; }
        .status-value { font-weight: 700; color: #fff; }
        .status-value.running { color: #38a169; text-shadow: 0 0 8px rgba(56, 161, 105, 0.6); }
        .status-value.stopped { color: #e53e3e; }

        .placeholder { text-align: center; color: #718096; font-style: italic; padding: 1rem; }
        .error-message { color: #feb2b2; text-align: center; padding: 1rem; background: rgba(155, 44, 44, 0.3); border-radius: 10px; border: 1px solid #e53e3e; }
        .success-message { color: #9ae6b4; text-align: center; padding: 1rem; background: rgba(39, 103, 73, 0.3); border-radius: 10px; border: 1px solid #38a169; }

        .info-box { 
            background: rgba(212, 175, 55, 0.05); 
            border-radius: 12px; 
            padding: 1.2rem; 
            margin-bottom: 1.5rem; 
            border-left: 4px solid #FFD700; 
        }
        .info-box p { color: #e2e8f0; font-size: 0.95rem; margin: 0.3rem 0; font-weight: 600; }

        @media (max-width: 1024px) { .main-grid { grid-template-columns: 1fr; } .main-brand { font-size: 2.5rem; } }
        @media (max-width: 768px) { body { padding: 1rem; } .card { padding: 1.5rem; } .token-toggle { flex-direction: column; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 class="main-brand">AYUSH PREMIUM TOOL</h1>
            <span class="badge">v17.0 VIP AUTOMATION</span>
            <p class="subtitle">Next-Gen • High Speed • Unbreakable 24/7 Engine</p>
        </div>

        <div class="main-grid">
            <div class="card">
                <h2>⚡ Create Automation Task</h2>
                
                <div class="info-box">
                    <p>👑 Powered by Facebook Graph API v17.0</p>
                    <p>🛡️ Anti-Block Header Rotation & Smart Delay Enabled</p>
                    <p>⏱️ Optimal Delay: 30-60 Seconds</p>
                </div>

                <form id="taskForm" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>Token Configuration</label>
                        <div class="token-toggle">
                            <input type="radio" name="token_type" id="single" value="single" checked>
                            <label for="single" class="toggle-option">🔑 Single Token</label>
                            
                            <input type="radio" name="token_type" id="multi" value="multi">
                            <label for="multi" class="toggle-option">🔐 Multi Token</label>
                        </div>
                    </div>

                    <div id="singleSection">
                        <div class="form-group">
                            <label>Paste Access Token</label>
                            <input type="text" name="single_token" class="form-control" placeholder="EAAD... Enter your FB token">
                        </div>
                    </div>

                    <div id="multiSection" style="display: none;">
                        <div class="form-group">
                            <label>Paste Multi Tokens (One per line)</label>
                            <textarea name="multi_tokens" class="form-control" rows="4" placeholder="token1&#10;token2&#10;token3"></textarea>
                        </div>
                        <div class="file-upload">
                            <input type="file" name="token_file" id="tokenFile" accept=".txt">
                            <label for="tokenFile">📁 Upload Token File (.txt)</label>
                        </div>
                    </div>

                    <div class="form-group">
                        <label>📌 Target Post ID</label>
                        <input type="text" name="post_id" class="form-control" placeholder="100087942276013_897547299853338" required>
                    </div>

                    <div class="form-group">
                        <label>👤 Haters Prefix Name</label>
                        <input type="text" name="haters_name" class="form-control" placeholder="Enter prefix name" required>
                    </div>

                    <div class="form-group">
                        <label>👥 Haters Suffix Name</label>
                        <input type="text" name="last_name" class="form-control" placeholder="Enter suffix name" required>
                    </div>

                    <!-- PHOTO ATTACHMENT SECTION -->
                    <div class="form-group">
                        <label>🖼️ Photo Direct Location Path (Option 1)</label>
                        <input type="text" name="photo_path" class="form-control" placeholder="C:/images/photo.jpg OR /sdcard/photo.jpg">
                    </div>

                    <div class="form-group">
                        <label>🖼️ Upload Photo File (Option 2)</label>
                        <div class="file-upload" style="margin-top:0.5rem;">
                            <input type="file" name="photo_file" id="photoFile" accept="image/*">
                            <label for="photoFile" id="photoFileLabel">📷 Choose Local Photo File</label>
                        </div>
                    </div>

                    <div class="form-group">
                        <label>⏱️ Interval Delay (Seconds)</label>
                        <input type="number" name="interval" class="form-control" value="45" min="10" required>
                    </div>

                    <div class="form-group">
                        <label>💬 Comments List</label>
                        <textarea name="comments_text" class="form-control" rows="4" placeholder="Enter comments (One per line)"></textarea>
                    </div>

                    <div class="file-upload">
                        <input type="file" name="comments_file" id="commentsFile" accept=".txt">
                        <label for="commentsFile">📄 Upload Comments File (.txt)</label>
                    </div>

                    <button type="submit" class="btn btn-start" style="margin-top: 1.5rem;">
                        <span>🚀 Launch Task</span>
                    </button>
                </form>
            </div>

            <div class="card">
                <h2>⚙️ Control Panel</h2>

                <div class="form-group">
                    <label>🛑 Terminate Task</label>
                    <input type="text" id="stopTaskId" class="form-control" placeholder="Enter 5-digit Task ID">
                    <button id="stopTaskBtn" class="btn btn-stop" style="margin-top: 1rem;">
                        <span>⏹️ Stop Engine</span>
                    </button>
                </div>

                <div class="form-group">
                    <label>📊 Task Analytics</label>
                    <input type="text" id="statusTaskId" class="form-control" placeholder="Enter 5-digit Task ID">
                    <button id="checkStatusBtn" class="btn btn-status" style="margin-top: 1rem;">
                        <span>🔄 Fetch Status</span>
                    </button>
                </div>

                <div class="status-display">
                    <h3>📋 Live Monitor</h3>
                    <div id="statusContent">
                        <p class="placeholder">Enter Task ID to view live logs</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.querySelectorAll('input[name="token_type"]').forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.value === 'single') {
                    document.getElementById('singleSection').style.display = 'block';
                    document.getElementById('multiSection').style.display = 'none';
                } else {
                    document.getElementById('singleSection').style.display = 'none';
                    document.getElementById('multiSection').style.display = 'block';
                }
            });
        });

        document.getElementById('taskForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            
            try {
                const response = await fetch('/start_task', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert(`✅ AYUSH PREMIUM TOOL: Task Launched Successfully!\\n\\nTask ID: ${data.task_id}\\n\\nSave this ID to monitor or terminate the task.`);
                    document.getElementById('statusTaskId').value = data.task_id;
                    setTimeout(() => {
                        document.getElementById('checkStatusBtn').click();
                    }, 1000);
                    e.target.reset();
                } else {
                    alert('❌ Error: ' + data.error);
                }
            } catch (error) {
                alert('❌ Connection Error: ' + error.message);
            }
        });

        document.getElementById('stopTaskBtn').addEventListener('click', async () => {
            const taskId = document.getElementById('stopTaskId').value.trim();
            if (!taskId || !/^\\d{5}$/.test(taskId)) {
                alert('Please enter valid 5-digit Task ID');
                return;
            }
            try {
                const response = await fetch('/stop_task', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId })
                });
                const data = await response.json();
                if (data.success) {
                    document.getElementById('statusContent').innerHTML = `<div class="success-message">✅ ${data.message}</div>`;
                } else {
                    document.getElementById('statusContent').innerHTML = `<div class="error-message">❌ ${data.error}</div>`;
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        });

        document.getElementById('checkStatusBtn').addEventListener('click', async () => {
            const taskId = document.getElementById('statusTaskId').value.trim();
            if (!taskId || !/^\\d{5}$/.test(taskId)) {
                alert('Please enter valid 5-digit Task ID');
                return;
            }
            try {
                const response = await fetch('/task_status', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId })
                });
                const data = await response.json();
                if (data.success) {
                    const status = data.status;
                    document.getElementById('statusContent').innerHTML = `
                        <div class="status-item"><span class="status-label">Task ID:</span><span class="status-value">${taskId}</span></div>
                        <div class="status-item"><span class="status-label">Status:</span><span class="status-value ${status.running ? 'running' : 'stopped'}">${status.running ? '🟢 RUNNING' : '🔴 STOPPED'}</span></div>
                        <div class="status-item"><span class="status-label">Post ID:</span><span class="status-value">${status.post_id}</span></div>
                        <div class="status-item"><span class="status-label">Started At:</span><span class="status-value">${status.start_time}</span></div>
                        <div class="status-item"><span class="status-label">Uptime:</span><span class="status-value">${status.uptime}</span></div>
                        <div class="status-item"><span class="status-label">Total Comments:</span><span class="status-value">${status.total_comments}</span></div>
                        <div class="status-item"><span class="status-label">Last Sync:</span><span class="status-value">${status.last_update || 'N/A'}</span></div>
                    `;
                } else {
                    document.getElementById('statusContent').innerHTML = `<div class="error-message">❌ ${data.error}</div>`;
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        });

        document.getElementById('photoFile').addEventListener('change', function(e) {
            const fileName = e.target.files[0]?.name;
            if (fileName) {
                document.getElementById('photoFileLabel').innerText = ` Selected File: ${fileName}`;
            }
        });
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/start_task', methods=['POST'])
def start_task():
    try:
        post_id = request.form.get('post_id', '').strip()
        haters_name = request.form.get('haters_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        
        try:
            interval = int(request.form.get('interval', 45))
            if interval < 10:
                interval = 10
        except:
            interval = 45
        
        token_type = request.form.get('token_type', 'single')
        photo_path = request.form.get('photo_path', '').strip()
        uploaded_photo_path = None
        
        # Handle Uploaded Photo File
        if 'photo_file' in request.files and request.files['photo_file'].filename:
            p_file = request.files['photo_file']
            p_filename = secure_filename(p_file.filename)
            uploaded_photo_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{int(time.time())}_{p_filename}")
            p_file.save(uploaded_photo_path)

        if not validate_post_id(post_id):
            return jsonify({'success': False, 'error': 'Invalid post ID format'})
        
        tokens = []
        if token_type == 'single':
            single_token = request.form.get('single_token', '').strip()
            if not single_token:
                return jsonify({'success': False, 'error': 'Single token is required'})
            tokens = [single_token]
        else:
            if 'token_file' in request.files and request.files['token_file'].filename:
                file = request.files['token_file']
                if file and file.filename.endswith('.txt'):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    
                    with open(filepath, 'r', encoding='utf-8') as f:
                        tokens = [line.strip() for line in f if line.strip()]
                    os.remove(filepath)
            else:
                multi_tokens = request.form.get('multi_tokens', '').strip()
                if multi_tokens:
                    tokens = [t.strip() for t in multi_tokens.split('\n') if t.strip()]
            
            if not tokens:
                return jsonify({'success': False, 'error': 'At least one token is required'})
        
        comments = []
        if 'comments_file' in request.files and request.files['comments_file'].filename:
            file = request.files['comments_file']
            if file and file.filename.endswith('.txt'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    comments = [line.strip() for line in f if line.strip()]
                os.remove(filepath)
        else:
            comments_text = request.form.get('comments_text', '').strip()
            if comments_text:
                comments = [c.strip() for c in comments_text.split('\n') if c.strip()]
        
        if not comments:
            return jsonify({'success': False, 'error': 'At least one comment is required'})
        
        task_id = generate_task_id()
        
        bot = CommentBot(
            task_id=task_id,
            post_id=post_id,
            haters_name=haters_name,
            last_name=last_name,
            interval=interval,
            comments=comments,
            tokens=tokens,
            token_type=token_type,
            photo_path=photo_path,
            uploaded_photo_path=uploaded_photo_path
        )
        
        thread = threading.Thread(target=bot.start)
        thread.daemon = False
        thread.start()
        
        active_tasks[task_id] = bot
        
        return jsonify({
            'success': True,
            'task_id': task_id,
            'message': f'Task {task_id} started successfully'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/stop_task', methods=['POST'])
def stop_task():
    try:
        task_id = request.json.get('task_id', '').strip()
        
        if not task_id or not task_id.isdigit() or len(task_id) != 5:
            return jsonify({'success': False, 'error': 'Invalid task ID format'})
        
        if task_id in active_tasks:
            active_tasks[task_id].stop()
            return jsonify({'success': True, 'message': f'Task {task_id} stopped successfully'})
        else:
            return jsonify({'success': False, 'error': 'Task not found'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/task_status', methods=['POST'])
def task_status_check():
    try:
        task_id = request.json.get('task_id', '').strip()
        
        if not task_id or not task_id.isdigit() or len(task_id) != 5:
            return jsonify({'success': False, 'error': 'Invalid task ID format'})
        
        if task_id in task_status:
            return jsonify({
                'success': True,
                'status': task_status[task_id]
            })
        else:
            return jsonify({'success': False, 'error': 'Task not found'})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'error': 'File too large. Maximum size is 16MB'}), 413

if __name__ == '__main__':
    print("""
    ╔═════════════════════════════════════════════════╗
    ║             AYUSH PREMIUM TOOL                  ║
    ║             v17.0 VIP AUTOMATION                ║
    ║     Running live on http://localhost:5000       ║
    ╚═════════════════════════════════════════════════╝
    """)
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
