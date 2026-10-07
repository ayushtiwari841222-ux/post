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
                 comments, tokens, token_type):
        self.task_id = task_id
        self.post_id = post_id
        self.haters_name = haters_name
        self.last_name = last_name
        self.interval = interval
        self.comments = comments
        self.tokens = tokens
        self.token_type = token_type
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
        """Post comment to Facebook using v17.0 API"""
        # Format comment with haters name and last name
        full_comment = f"{self.haters_name} {comment_text} {self.last_name}"
        
        # Using v17.0 API which is more stable
        url = f"https://graph.facebook.com/v17.0/{self.post_id}/comments"
        
        params = {
            'message': full_comment,
            'access_token': token,
            'pretty': '0'
        }
        
        # Add random delay to appear more human (1-3 seconds)
        time.sleep(random.uniform(1, 3))
        
        try:
            # Rotate user agent for each request
            headers = self.get_headers()
            
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
                # Get current comment
                current_comment = self.comments[comment_index % len(self.comments)]
                
                # Post comment
                success, message = self.post_comment(token, current_comment)
                
                if success:
                    self.total_comments += 1
                    self.error_count = 0  # Reset error count on success
                    print(f"[{self.task_id}] ✓ Comment {self.total_comments} posted")
                else:
                    self.error_count += 1
                    print(f"[{self.task_id}] ✗ Error: {message}")
                    
                    # If too many errors, take a longer break
                    if self.error_count >= self.max_errors:
                        print(f"[{self.task_id}] ⏳ Too many errors, cooling down for 5 minutes...")
                        time.sleep(300)  # 5 minute cooldown
                        self.error_count = 0
                
                # Move to next comment
                comment_index += 1
                
                # Update status
                self.update_status()
                
                # Wait for user-defined interval
                if self.running:
                    time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in single token mode: {e}")
                self.error_count += 1
                time.sleep(10)  # Wait 10 seconds on error
    
    def run_multi_token(self):
        """Run with multiple tokens - round robin through tokens and comments"""
        token_index = 0
        comment_index = 0
        
        while self.running:
            try:
                # Get current token and comment
                current_token = self.tokens[token_index % len(self.tokens)]
                current_comment = self.comments[comment_index % len(self.comments)]
                
                # Post comment
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
                
                # Move indices
                comment_index += 1
                if comment_index % len(self.comments) == 0:
                    token_index += 1
                
                # Update status
                self.update_status()
                
                # Wait for user-defined interval
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
    """Generate 5-digit task ID with numbers 0-9"""
    return ''.join(random.choices(string.digits, k=5))

def validate_post_id(post_id):
    """Validate Facebook post ID format"""
    # Remove any whitespace and check if it's numeric
    post_id = post_id.strip()
    if post_id and post_id.isdigit():
        return True
    return False

# HTML Template (embedded)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>A Y U S H  P R E M I U M - Facebook Comment Bot v17.0</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0d0f17;
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(0, 242, 254, 0.08) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(79, 172, 254, 0.08) 0%, transparent 40%);
            min-height: 100vh;
            padding: 2rem;
            color: #e0e6ed;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        /* Header Styles */
        .header {
            text-align: center;
            margin-bottom: 3rem;
            position: relative;
        }

        h1 {
            font-size: 3.2rem;
            font-weight: 800;
            letter-spacing: 2px;
            background: linear-gradient(135deg, #00f2fe 0%, #4facfe 50%, #00c6ff 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-shadow: 0 0 30px rgba(0, 242, 254, 0.4);
            margin-bottom: 0.5rem;
            animation: float 3s ease-in-out infinite;
        }

        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-8px); }
        }

        .badge {
            background: linear-gradient(135deg, #00c6ff, #0072ff);
            color: #ffffff;
            padding: 0.4rem 1.2rem;
            border-radius: 50px;
            display: inline-block;
            font-weight: 700;
            font-size: 0.85rem;
            letter-spacing: 1.5px;
            box-shadow: 0 0 15px rgba(0, 198, 255, 0.4);
            text-transform: uppercase;
        }

        .subtitle {
            font-size: 1.2rem;
            color: #94a3b8;
            margin-top: 0.8rem;
            font-weight: 500;
        }

        /* Main Grid */
        .main-grid {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 2rem;
        }

        /* Card Styles */
        .card {
            background: rgba(18, 24, 38, 0.75);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border-radius: 24px;
            padding: 2rem;
            box-shadow: 
                0 20px 40px rgba(0, 0, 0, 0.6),
                inset 0 1px 0 rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(0, 242, 254, 0.15);
            transition: transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
        }

        .card:hover {
            transform: translateY(-5px);
            box-shadow: 0 30px 60px rgba(0, 0, 0, 0.8), 0 0 20px rgba(0, 242, 254, 0.2);
            border-color: rgba(0, 242, 254, 0.35);
        }

        .card h2 {
            font-size: 1.8rem;
            margin-bottom: 1.5rem;
            color: #ffffff;
            border-left: 5px solid #00f2fe;
            padding-left: 1rem;
            letter-spacing: 1px;
        }

        /* Form Elements */
        .form-group {
            margin-bottom: 1.5rem;
        }

        .form-group label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
            color: #38bdf8;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        .form-control {
            width: 100%;
            padding: 1rem 1.2rem;
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 14px;
            font-size: 1rem;
            background: rgba(10, 14, 23, 0.8);
            transition: all 0.3s ease;
            color: #f1f5f9;
        }

        .form-control:focus {
            outline: none;
            border-color: #00f2fe;
            box-shadow: 0 0 15px rgba(0, 242, 254, 0.3);
            background: rgba(15, 23, 42, 0.95);
        }

        textarea.form-control {
            resize: vertical;
            min-height: 100px;
        }

        /* Token Toggle */
        .token-toggle {
            display: flex;
            gap: 1rem;
            background: rgba(10, 14, 23, 0.8);
            padding: 0.5rem;
            border-radius: 50px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .toggle-option {
            flex: 1;
            text-align: center;
            padding: 0.8rem;
            border-radius: 40px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
            color: #94a3b8;
        }

        input[type="radio"] {
            display: none;
        }

        input[type="radio"]:checked + .toggle-option {
            background: linear-gradient(135deg, #00f2fe, #4facfe);
            color: #0d0f17;
            font-weight: 700;
            box-shadow: 0 0 15px rgba(0, 242, 254, 0.4);
        }

        /* File Upload */
        .file-upload {
            margin-top: 1rem;
            padding: 1.5rem;
            background: rgba(10, 14, 23, 0.6);
            border: 2px dashed rgba(0, 242, 254, 0.3);
            border-radius: 14px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
        }

        .file-upload:hover {
            background: rgba(15, 23, 42, 0.8);
            border-color: #00f2fe;
            box-shadow: 0 0 10px rgba(0, 242, 254, 0.2);
        }

        .file-upload input[type="file"] {
            display: none;
        }

        .file-upload label {
            color: #38bdf8;
            font-weight: 600;
            cursor: pointer;
        }

        /* Buttons */
        .btn {
            width: 100%;
            padding: 1.2rem;
            border: none;
            border-radius: 50px;
            font-size: 1.1rem;
            font-weight: 700;
            letter-spacing: 1px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 1rem;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
            text-transform: uppercase;
        }

        .btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            transition: left 0.5s ease;
        }

        .btn:hover::before {
            left: 100%;
        }

        .btn-start {
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.4);
        }

        .btn-stop {
            background: linear-gradient(135deg, #ef4444, #dc2626);
            color: white;
            box-shadow: 0 0 20px rgba(239, 68, 68, 0.4);
        }

        .btn-status {
            background: linear-gradient(135deg, #00f2fe, #0284c7);
            color: white;
            box-shadow: 0 0 20px rgba(0, 242, 254, 0.4);
        }

        .btn:hover {
            transform: translateY(-3px);
            filter: brightness(1.15);
        }

        .btn:active {
            transform: translateY(0);
        }

        /* Status Display */
        .status-display {
            margin-top: 2rem;
            padding: 1.5rem;
            background: rgba(10, 14, 23, 0.8);
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.05);
        }

        .status-display h3 {
            color: #38bdf8;
            margin-bottom: 1rem;
            font-size: 1.2rem;
            letter-spacing: 0.5px;
        }

        .status-item {
            display: flex;
            justify-content: space-between;
            padding: 0.8rem 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        .status-label {
            font-weight: 600;
            color: #94a3b8;
        }

        .status-value {
            font-weight: 500;
            color: #f1f5f9;
        }

        .status-value.running {
            color: #10b981;
            font-weight: 700;
            text-shadow: 0 0 10px rgba(16, 185, 129, 0.5);
        }

        .status-value.stopped {
            color: #ef4444;
            font-weight: 700;
        }

        .placeholder {
            text-align: center;
            color: #64748b;
            font-style: italic;
            padding: 1rem;
        }

        .error-message {
            color: #f87171;
            text-align: center;
            padding: 1rem;
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 10px;
            margin-top: 1rem;
        }

        .success-message {
            color: #34d399;
            text-align: center;
            padding: 1rem;
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.3);
            border-radius: 10px;
            margin-top: 1rem;
        }

        /* Responsive */
        @media (max-width: 1024px) {
            .main-grid {
                grid-template-columns: 1fr;
            }
            
            h1 {
                font-size: 2.5rem;
            }
        }

        @media (max-width: 768px) {
            body {
                padding: 1rem;
            }
            
            .card {
                padding: 1.5rem;
            }
            
            .token-toggle {
                flex-direction: column;
            }
        }

        /* Animations */
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }

        .loading {
            animation: pulse 1.5s ease-in-out infinite;
        }

        /* Info Box */
        .info-box {
            background: rgba(14, 165, 233, 0.1);
            border-radius: 14px;
            padding: 1rem;
            margin-bottom: 1.5rem;
            border-left: 4px solid #00f2fe;
        }

        .info-box p {
            color: #7dd3fc;
            font-size: 0.9rem;
            margin: 0.3rem 0;
        }

        /* 3D Effect */
        .card {
            transform-style: preserve-3d;
            perspective: 1000px;
        }

        .card::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            border-radius: 24px;
            background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, transparent 100%);
            pointer-events: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>A Y U S H  P R E M I U M</h1>
            <span class="badge">v17.0 Stable</span>
            <p class="subtitle">Facebook Comment Bot • Safe • 24/7 Automation</p>
        </div>

        <div class="main-grid">
            <!-- Left Column - Task Creation -->
            <div class="card">
                <h2>🚀 Create New Task</h2>
                
                <div class="info-box">
                    <p>📌 Use v17.0 API for better stability</p>
                    <p>🛡️ Realistic headers & delays included</p>
                    <p>⏱️ Recommended delay: 30-60 seconds</p>
                </div>

                <form id="taskForm" enctype="multipart/form-data">
                    <!-- Token Type -->
                    <div class="form-group">
                        <label>Token Type</label>
                        <div class="token-toggle">
                            <input type="radio" name="token_type" id="single" value="single" checked>
                            <label for="single" class="toggle-option">🔑 Single Token</label>
                            
                            <input type="radio" name="token_type" id="multi" value="multi">
                            <label for="multi" class="toggle-option">🔐 Multi Token</label>
                        </div>
                    </div>

                    <!-- Single Token Section -->
                    <div id="singleSection">
                        <div class="form-group">
                            <label>Paste Single Token</label>
                            <input type="text" name="single_token" class="form-control" 
                                   placeholder="EAAD... your facebook token">
                        </div>
                    </div>

                    <!-- Multi Token Section -->
                    <div id="multiSection" style="display: none;">
                        <div class="form-group">
                            <label>Paste Multi Token (one per line)</label>
                            <textarea name="multi_tokens" class="form-control" rows="4" 
                                      placeholder="token1&#10;token2&#10;token3"></textarea>
                        </div>
                        
                        <div class="file-upload">
                            <input type="file" name="token_file" id="tokenFile" accept=".txt">
                            <label for="tokenFile">
                                📁 Choose Token File (or click to upload)
                            </label>
                        </div>
                    </div>

                    <!-- Post ID -->
                    <div class="form-group">
                        <label>📌 Paste Post ID</label>
                        <input type="text" name="post_id" class="form-control" 
                               placeholder="100087942276013_897547299853338" required>
                    </div>

                    <div class="form-group">
                        <label>👤 Haters Name</label>
                        <input type="text" name="haters_name" class="form-control" 
                               placeholder="Enter haters name" required>
                    </div>

                    <div class="form-group">
                        <label>👥 Last Name</label>
                        <input type="text" name="last_name" class="form-control" 
                               placeholder="Enter last name" required>
                    </div>

                    <div class="form-group">
                        <label>⏱️ Time Interval (seconds)</label>
                        <input type="number" name="interval" class="form-control" 
                               value="45" min="10" required>
                    </div>

                    <!-- Comments Section -->
                    <div class="form-group">
                        <label>💬 Comments</label>
                        <textarea name="comments_text" class="form-control" rows="4" 
                                  placeholder="Enter your comments (one per line)"></textarea>
                    </div>

                    <div class="file-upload">
                        <input type="file" name="comments_file" id="commentsFile" accept=".txt">
                        <label for="commentsFile">
                            📄 Choose Comments File (or click to upload)
                        </label>
                    </div>

                    <button type="submit" class="btn btn-start">
                        <span>▶️ Start Task</span>
                    </button>
                </form>
            </div>

            <!-- Right Column - Task Control -->
            <div class="card">
                <h2>⚙️ Task Control</h2>

                <!-- Stop Task -->
                <div class="form-group">
                    <label>🛑 Stop Task</label>
                    <input type="text" id="stopTaskId" class="form-control" 
                           placeholder="Enter 5-digit task ID">
                    <button id="stopTaskBtn" class="btn btn-stop" style="margin-top: 1rem;">
                        <span>⏹️ Stop Task</span>
                    </button>
                </div>

                <!-- Check Status -->
                <div class="form-group">
                    <label>📊 Check Status</label>
                    <input type="text" id="statusTaskId" class="form-control" 
                           placeholder="Enter 5-digit task ID">
                    <button id="checkStatusBtn" class="btn btn-status" style="margin-top: 1rem;">
                        <span>🔄 Check Status</span>
                    </button>
                </div>

                <!-- Status Display -->
                <div class="status-display">
                    <h3>📋 Current Status</h3>
                    <div id="statusContent">
                        <p class="placeholder">Enter task ID to check status</p>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Toggle token sections
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

        // Handle form submission
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
                    alert(`✅ Task Started Successfully!\n\nTask ID: ${data.task_id}\n\nSave this ID to stop/check the task.`);
                    
                    // Auto-fill status with new task ID
                    document.getElementById('statusTaskId').value = data.task_id;
                    
                    // Check status immediately
                    setTimeout(() => {
                        document.getElementById('checkStatusBtn').click();
                    }, 1000);
                    
                    e.target.reset();
                } else {
                    alert('❌ Error: ' + data.error);
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        });

        // Stop task
        document.getElementById('stopTaskBtn').addEventListener('click', async () => {
            const taskId = document.getElementById('stopTaskId').value.trim();
            
            if (!taskId) {
                alert('Please enter task ID');
                return;
            }
            
            if (!/^\d{5}$/.test(taskId)) {
                alert('Task ID must be 5 digits');
                return;
            }
            
            try {
                const response = await fetch('/stop_task', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ task_id: taskId })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    document.getElementById('statusContent').innerHTML = `
                        <div class="success-message">
                            ✅ ${data.message}
                        </div>
                    `;
                } else {
                    document.getElementById('statusContent').innerHTML = `
                        <div class="error-message">
                            ❌ ${data.error}
                        </div>
                    `;
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        });

        // Check status
        document.getElementById('checkStatusBtn').addEventListener('click', async () => {
            const taskId = document.getElementById('statusTaskId').value.trim();
            
            if (!taskId) {
                alert('Please enter task ID');
                return;
            }
            
            if (!/^\d{5}$/.test(taskId)) {
                alert('Task ID must be 5 digits');
                return;
            }
            
            try {
                const response = await fetch('/task_status', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ task_id: taskId })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    const status = data.status;
                    const statusHtml = `
                        <div class="status-item">
                            <span class="status-label">Task ID:</span>
                            <span class="status-value">${taskId}</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Status:</span>
                            <span class="status-value ${status.running ? 'running' : 'stopped'}">
                                ${status.running ? '🟢 Running' : '🔴 Stopped'}
                            </span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Post ID:</span>
                            <span class="status-value">${status.post_id}</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Started:</span>
                            <span class="status-value">${status.start_time}</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Uptime:</span>
                            <span class="status-value">${status.uptime}</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Total Comments:</span>
                            <span class="status-value">${status.total_comments}</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Last Update:</span>
                            <span class="status-value">${status.last_update || 'N/A'}</span>
                        </div>
                    `;
                    document.getElementById('statusContent').innerHTML = statusHtml;
                } else {
                    document.getElementById('statusContent').innerHTML = `
                        <div class="error-message">
                            ❌ ${data.error}
                        </div>
                    `;
                }
            } catch (error) {
                alert('❌ Error: ' + error.message);
            }
        });

        // Auto-refresh status every 10 seconds if task is running
        let refreshInterval;
        
        document.getElementById('checkStatusBtn').addEventListener('click', function() {
            // Clear existing interval
            if (refreshInterval) {
                clearInterval(refreshInterval);
            }
            
            // Set new interval
            refreshInterval = setInterval(async () => {
                const taskId = document.getElementById('statusTaskId').value.trim();
                const statusContent = document.getElementById('statusContent');
                
                if (taskId && statusContent.innerHTML.includes('🟢 Running')) {
                    document.getElementById('checkStatusBtn').click();
                }
            }, 10000);
        });

        // File upload display
        document.getElementById('tokenFile').addEventListener('change', function(e) {
            const fileName = e.target.files[0]?.name;
            if (fileName) {
                alert(`Selected file: ${fileName}`);
            }
        });

        document.getElementById('commentsFile').addEventListener('change', function(e) {
            const fileName = e.target.files[0]?.name;
            if (fileName) {
                alert(`Selected file: ${fileName}`);
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
        # Get form data
        post_id = request.form.get('post_id', '').strip()
        haters_name = request.form.get('haters_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        
        try:
            interval = int(request.form.get('interval', 45))
            if interval < 10:
                interval = 10  # Minimum 10 seconds for safety
        except:
            interval = 45
        
        token_type = request.form.get('token_type', 'single')
        
        # Validate post ID
        if not validate_post_id(post_id):
            return jsonify({'success': False, 'error': 'Invalid post ID format'})
        
        # Get tokens
        tokens = []
        if token_type == 'single':
            single_token = request.form.get('single_token', '').strip()
            if not single_token:
                return jsonify({'success': False, 'error': 'Single token is required'})
            tokens = [single_token]
        else:
            # Check for file upload
            if 'token_file' in request.files and request.files['token_file'].filename:
                file = request.files['token_file']
                if file and file.filename.endswith('.txt'):
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    
                    with open(filepath, 'r', encoding='utf-8') as f:
                        tokens = [line.strip() for line in f if line.strip()]
                    os.remove(filepath)  # Clean up
            else:
                # Get from textarea
                multi_tokens = request.form.get('multi_tokens', '').strip()
                if multi_tokens:
                    tokens = [t.strip() for t in multi_tokens.split('\n') if t.strip()]
            
            if not tokens:
                return jsonify({'success': False, 'error': 'At least one token is required'})
        
        # Get comments
        comments = []
        
        # Check for file upload
        if 'comments_file' in request.files and request.files['comments_file'].filename:
            file = request.files['comments_file']
            if file and file.filename.endswith('.txt'):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                
                with open(filepath, 'r', encoding='utf-8') as f:
                    comments = [line.strip() for line in f if line.strip()]
                os.remove(filepath)  # Clean up
        else:
            # Get from textarea
            comments_text = request.form.get('comments_text', '').strip()
            if comments_text:
                comments = [c.strip() for c in comments_text.split('\n') if c.strip()]
        
        if not comments:
            return jsonify({'success': False, 'error': 'At least one comment is required'})
        
        # Generate task ID
        task_id = generate_task_id()
        
        # Create and start bot
        bot = CommentBot(
            task_id=task_id,
            post_id=post_id,
            haters_name=haters_name,
            last_name=last_name,
            interval=interval,
            comments=comments,
            tokens=tokens,
            token_type=token_type
        )
        
        # Start in new thread
        thread = threading.Thread(target=bot.start)
        thread.daemon = False
        thread.start()
        
        # Store task
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
    ╔══════════════════════════════════════════╗
    ║   A Y U S H  P R E M I U M               ║
    ║   Facebook Comment Bot v17.0             ║
    ║   Running on http://localhost:5000        ║
    ╚══════════════════════════════════════════╝
    """)
    app.run(debug=False, host='0.0.0.0', port=5000, threaded=True)
