import json
import os
import signal
import sqlite3
import threading
import time

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 8000
PATH = 'forwardedChats'

# Set this to an empty string if you don't want the entire packet dump. The file gets large pretty quickly.
DATA_DIR = './data/'
DATA_FILE = f'{DATA_DIR}data.ndjson'
DB_FILE = f'{DATA_DIR}chat_messages.db'

def init_db():
    if not os.path.exists(DB_FILE):
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute('''
                CREATE TABLE chat_messages (
                    id TEXT PRIMARY KEY NOT NULL,
                    videoId TEXT NOT NULL,
                    authorName TEXT NOT NULL,
                    authorChannelId TEXT NOT NULL,
                    text TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                )
            ''')
            conn.commit()

def insert_chat_message(video_id, message):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute('''
            INSERT INTO chat_messages (id, videoId, authorName, authorChannelId, text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            message.get("id", ""),
            video_id,
            message.get("authorName", ""),
            message.get("authorExternalChannelId", ""),
            message.get("text", ""),
            # Convert microseconds to milliseconds, to conform to Unix timestamp formats.
            int(message.get("timestampUsec", 0)) // 1000
        ))
        conn.commit()

def extract_chat_data(data):
    results = []

    try:
        actions = data["continuationContents"]["liveChatContinuation"]["actions"]
    except KeyError as e:
        return results
    except TypeError as e:
        return results

    for action in actions:
        chat_item = action.get("addChatItemAction", {}).get("item", {})
        renderer = chat_item.get("liveChatTextMessageRenderer", {})

        id = renderer.get("id", {})
        message_runs = renderer.get("message", {}).get("runs", [])

        # We want to do some custom handling on the messags runs (the seperate segments of one chat message), since it can be made up of several types of data.
        # Emoji are the most interesting (and annoying) aspects to consider, especially since channel-specific custom ones have no direct analogues.
        message_parts = []
        for run in message_runs:
            if "text" in run:
                message_parts.append(run["text"])
            elif "emoji" in run:
                emoji = run["emoji"]
                if "shortcuts" in emoji and emoji.get("isCustomEmoji"):
                    shortcut = emoji["shortcuts"][0] if emoji["shortcuts"] else "custom"
                    message_parts.append(f":{shortcut.strip(':')}:")
                elif "emojiId" in emoji:
                    message_parts.append(emoji.get("emojiId", ""))
                else:
                    message_parts.append("[emoji]")

        message_text = "".join(message_parts)

        author_name = renderer.get("authorName", {}).get("simpleText", "")
        author_channel_id = renderer.get("authorExternalChannelId", "")
        timestamp_usec = renderer.get("timestampUsec", "")

        author_badges = renderer.get("authorBadges", [])
        author_photo_url = ""
        if author_badges:
            author_photo_url = renderer.get("authorPhoto", {}).get("thumbnails", [{}])[0].get("url", "")

        result = {
            "id": id,
            "text": message_text,
            "authorName": author_name,
            "authorExternalChannelId": author_channel_id,
            "timestampUsec": timestamp_usec,
            "authorPhotoUrl": author_photo_url
        }

        results.append(result)

    return results

class ChatInterceptor(BaseHTTPRequestHandler):
    def _send_headers(self, code=200, content_type="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        if urlparse(self.path).path != f"/{PATH}":
            self._send_headers(404)
            self.wfile.write(b"File Not Found")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            raw_data = self.rfile.read(length)
            payload = json.loads(raw_data)
            
            video_id = payload.get("videoId", "")
            data = payload.get("data", [])

            # Store full packet if desired.
            if DATA_FILE != "":
                with open(DATA_FILE, 'a', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False)
                    f.write('\n')
            
            # Extract chat messages details that we're interested in.
            messages = extract_chat_data(data)

            for msg in messages:
                insert_chat_message(video_id, msg)
                print(f"[Saved] {msg['authorName']}: {msg['text']}")

            self._send_headers()
            self.wfile.write(json.dumps({ "success": True }).encode())

        except Exception as e:
            self._send_headers(400)
            self.wfile.write(json.dumps({ "error": str(e) }).encode())

def log_status():
    print("[+] Server running. Waiting for forwarded packets...")

def start_server():
    httpd = HTTPServer(('127.0.0.1', PORT), ChatInterceptor)
    print(f"[+] Listening at http://localhost:{PORT}/")
    httpd.serve_forever()

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    
    init_db()

    with open(DATA_FILE, "w+") as f:
        pass

    signal.signal(signal.SIGINT, lambda *_: (print("\n[!] Shutdown signal received."), exit(0)))
    threading.Timer(3, log_status).start()
    start_server()
