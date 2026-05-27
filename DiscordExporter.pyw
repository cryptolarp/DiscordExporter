import customtkinter as ctk
import tkinter as tk
import requests
import json
import os
import time
import threading
import datetime
import re
import csv
import io

TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".dce_token.json")

def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
            return data.get("token", "")
        except:
            return ""
    return ""

def save_token(token):
    with open(TOKEN_FILE, "w") as f:
        json.dump({"token": token}, f)

def delete_token():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)

API_BASE = "https://discord.com/api/v10"
HEADERS_TEMPLATE = {
    "User-Agent": "DiscordChatExporter/1.0"
}

def fetch_messages(token, channel_id, limit, progress_callback, status_callback):
    headers = HEADERS_TEMPLATE.copy()
    headers["Authorization"] = token

    all_messages = []
    before = None
    total_fetched = 0
    stop = False

    while not stop:
        params = {"limit": 100}
        if before:
            params["before"] = before

        resp = requests.get(f"{API_BASE}/channels/{channel_id}/messages",
                           headers=headers, params=params)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            status_callback(f"Rate limited, waiting {retry_after}s...")
            time.sleep(retry_after)
            continue

        if resp.status_code != 200:
            raise Exception(f"API error {resp.status_code}: {resp.text}")

        batch = resp.json()
        if not batch:
            break

        all_messages.extend(batch)
        total_fetched = len(all_messages)
        if limit and total_fetched >= limit:
            all_messages = all_messages[:limit]
            stop = True

        before = batch[-1]["id"]
        progress_callback(total_fetched)

        if not limit and len(batch) < 100:
            stop = True

        time.sleep(0.6)

    all_messages.reverse()
    return all_messages

def escape_html(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;"))

def convert_markdown(text):
    text = re.sub(r"```(\w*)\n?(.+?)```", r"<pre><code>\2</code></pre>", text, flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"_(.+?)_", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)
    text = re.sub(r"\|\|(.+?)\|\|", r'<span class="spoiler">\1</span>', text)
    text = text.replace("\n", "<br>")
    return text

def generate_html(messages, channel_id):
    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head><meta charset='utf-8'><title>Discord Chat Export</title>",
        "<style>",
        "body { background-color: #36393f; color: #dcddde; font-family: 'Whitney', 'Helvetica Neue', Helvetica, Arial, sans-serif; margin: 0; padding: 20px; }",
        ".message { display: flex; margin-bottom: 16px; padding: 8px 0; border-bottom: 1px solid #42464d; }",
        ".avatar { width: 40px; height: 40px; border-radius: 50%; margin-right: 16px; }",
        ".content { max-width: calc(100% - 56px); }",
        ".author { font-weight: 600; margin-bottom: 4px; }",
        ".timestamp { font-size: 0.75rem; color: #72767d; margin-left: 8px; }",
        ".text { font-size: 0.9375rem; line-height: 1.375; word-wrap: break-word; white-space: pre-wrap; }",
        "code { background-color: #202225; padding: 2px 4px; border-radius: 3px; font-family: 'Consolas', 'Courier New', monospace; }",
        "pre { background-color: #202225; padding: 8px; border-radius: 4px; overflow-x: auto; }",
        "pre code { background: none; padding: 0; }",
        ".spoiler { background-color: #202225; color: transparent; border-radius: 3px; }",
        ".spoiler:hover { color: inherit; }",
        "</style></head><body>",
        f"<h2>Channel ID: {channel_id}</h2>"
    ]

    for msg in messages:
        author = msg.get("author", {})
        username = escape_html(author.get("username", "Unknown"))
        avatar_url = author.get("avatar")
        if avatar_url:
            avatar_url = f"https://cdn.discordapp.com/avatars/{author['id']}/{avatar_url}.png?size=40"
        else:
            avatar_url = "https://cdn.discordapp.com/embed/avatars/0.png"

        timestamp = msg.get("timestamp", "")
        try:
            dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            ts_formatted = dt.strftime("%d/%m/%Y %H:%M")
        except:
            ts_formatted = timestamp

        content = msg.get("content", "")
        content = escape_html(content)
        content = convert_markdown(content)

        html_parts.append(
            f'<div class="message">'
            f'<img class="avatar" src="{avatar_url}" alt="avatar">'
            f'<div class="content">'
            f'<div class="author">{username}<span class="timestamp">{ts_formatted}</span></div>'
            f'<div class="text">{content}</div>'
            f'</div></div>'
        )

    html_parts.append("</body></html>")
    return "\n".join(html_parts)

def generate_txt(messages):
    lines = []
    for msg in messages:
        author = msg.get("author", {}).get("username", "Unknown")
        timestamp = msg.get("timestamp", "")
        try:
            dt = datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            ts = dt.strftime("%d/%m/%Y %H:%M")
        except:
            ts = timestamp
        content = msg.get("content", "")
        lines.append(f"[{ts}] {author}: {content}")
    return "\n".join(lines)

def generate_csv(messages):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp", "Author ID", "Author Name", "Content"])
    for msg in messages:
        author = msg.get("author", {})
        writer.writerow([
            msg.get("timestamp", ""),
            author.get("id", ""),
            author.get("username", "Unknown"),
            msg.get("content", "")
        ])
    return output.getvalue()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Discord Chat Exporter")
        self.geometry("600x520")
        self.minsize(550, 450)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.main_frame = ctk.CTkFrame(self, fg_color="#1a1a1a", corner_radius=15)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.header = ctk.CTkLabel(
            self.main_frame, text="Discord Chat Exporter",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.header.pack(pady=(15, 5))
        self.token_label = ctk.CTkLabel(self.main_frame, text="Discord Token")
        self.token_label.pack(anchor="w", padx=30)
        self.token_entry = ctk.CTkEntry(
            self.main_frame, show="*", placeholder_text="Paste your token here",
            height=35, corner_radius=8
        )
        self.token_entry.pack(padx=30, pady=(5, 5), fill="x")

        self.remember_var = ctk.BooleanVar(value=False)
        self.remember_check = ctk.CTkCheckBox(
            self.main_frame, text="Remember token (saved locally)",
            variable=self.remember_var
        )
        self.remember_check.pack(padx=30, anchor="w", pady=(0, 10))

        self.channel_label = ctk.CTkLabel(self.main_frame, text="Channel ID")
        self.channel_label.pack(anchor="w", padx=30)
        self.channel_entry = ctk.CTkEntry(
            self.main_frame, placeholder_text="Enter channel ID",
            height=35, corner_radius=8
        )
        self.channel_entry.pack(padx=30, pady=(5, 10), fill="x")

        self.limit_label = ctk.CTkLabel(self.main_frame, text="Number of messages (leave empty for all)")
        self.limit_label.pack(anchor="w", padx=30)
        self.limit_entry = ctk.CTkEntry(
            self.main_frame, placeholder_text="e.g. 500",
            height=35, corner_radius=8, width=120
        )
        self.limit_entry.pack(padx=30, anchor="w", pady=(5, 10))

        self.format_label = ctk.CTkLabel(self.main_frame, text="Export format")
        self.format_label.pack(anchor="w", padx=30, pady=(0, 5))
        self.format_var = ctk.StringVar(value="html")

        format_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        format_frame.pack(padx=30, pady=(0, 10), fill="x")

        for text, value in [("HTML", "html"), ("TXT", "txt"), ("CSV", "csv")]:
            rb = ctk.CTkRadioButton(
                format_frame, text=text, variable=self.format_var, value=value,
                fg_color="#1f6aa5", hover_color="#144870"
            )
            rb.pack(side="left", padx=10)

        self.export_button = ctk.CTkButton(
            self.main_frame, text="Export", command=self.start_export,
            fg_color="#2563eb", hover_color="#1d4ed8",
            corner_radius=8, height=38, font=ctk.CTkFont(weight="bold")
        )
        self.export_button.pack(pady=(15, 10))

        self.progress = ctk.CTkProgressBar(self.main_frame, height=10, corner_radius=5)
        self.progress.pack(padx=30, fill="x", pady=(5, 5))
        self.progress.set(0)

        self.status_label = ctk.CTkLabel(
            self.main_frame, text="", text_color="gray",
            font=ctk.CTkFont(size=12)
        )
        self.status_label.pack(pady=(0, 15))

        self.load_saved_token()

    def load_saved_token(self):
        token = load_token()
        if token:
            self.token_entry.insert(0, token)
            self.remember_var.set(True)

    def start_export(self):
        self.export_button.configure(state="disabled")
        self.status_label.configure(text="")
        self.progress.set(0)

        token = self.token_entry.get().strip()
        channel_id = self.channel_entry.get().strip()
        limit_str = self.limit_entry.get().strip()
        export_format = self.format_var.get()

        if not token:
            self.show_error("Token cannot be empty.")
            return
        if not channel_id.isdigit():
            self.show_error("Channel ID must be a numeric ID.")
            return
        if limit_str:
            if not limit_str.isdigit():
                self.show_error("Message limit must be a number.")
                return
            limit = int(limit_str)
            if limit <= 0:
                self.show_error("Message limit must be positive.")
                return
        else:
            limit = None

        if self.remember_var.get():
            save_token(token)
        else:
            delete_token()

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = os.path.join(os.getcwd(), f"channel_{channel_id}_{timestamp}.{export_format}")

        self.progress.start()
        self.animate_status("Connecting...", "gray")

        thread = threading.Thread(target=self.fetch_thread,
                                  args=(token, channel_id, limit, export_format, export_path))
        thread.daemon = True
        thread.start()

    def fetch_thread(self, token, channel_id, limit, export_format, export_path):
        try:
            def progress_cb(fetched):
                self.after(0, self.update_fetched_count, fetched)

            def status_cb(msg):
                self.after(0, self.animate_status, msg, "gray")

            messages = fetch_messages(token, channel_id, limit, progress_cb, status_cb)

            if not messages:
                self.after(0, self.export_finished, False, "No messages found in this channel.")
                return

            if export_format == "html":
                content = generate_html(messages, channel_id)
            elif export_format == "txt":
                content = generate_txt(messages)
            elif export_format == "csv":
                content = generate_csv(messages)
            else:
                raise ValueError("Unsupported format")

            with open(export_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.after(0, self.export_finished, True,
                       f"Saved as {os.path.basename(export_path)}")
        except Exception as e:
            self.after(0, self.export_finished, False, f"Error: {str(e)}")

    def update_fetched_count(self, fetched):
        self.animate_status(f"Fetched {fetched} messages...", "gray")

    def animate_status(self, text, color):
        self.status_label.configure(text=text, text_color=color)
        self.progress.configure(progress_color="#1f6aa5")
        self.after(80, lambda: self.progress.configure(progress_color="#2563eb"))

    def export_finished(self, success, message):
        self.progress.stop()
        self.export_button.configure(state="normal")
        if success:
            color = "#4ade80"
        else:
            color = "#f87171"
        self.status_label.configure(text=message, text_color=color)
        if not success:
            self.show_error(message)

    def show_error(self, msg):
        self.export_button.configure(state="normal")
        self.status_label.configure(text=msg, text_color="#f87171")

if __name__ == "__main__":
    app = App()
    app.mainloop()