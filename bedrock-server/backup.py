#!/usr/bin/env python3
"""
BDS Telegram Backup System
- Backs up world when no players online
- Restores from Telegram on startup if world missing
- Chunks to 10MB for Telegram limits
"""
import os
import re
import sys
import time
import json
import zipfile
import hashlib
import shutil
import threading
import requests
from datetime import datetime

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.environ.get('TELEGRAM_CHANNEL_ID')
CHECK_INTERVAL = 300       # 5 minutes
BACKUP_INTERVAL = 1800     # 30 min between backups
IDLE_MINUTES = 5
CHUNK_SIZE = 10 * 1024 * 1024  # 10MB
STATE_FILE = '/data/backup_state.json'
TEMP_DIR = '/data/backup_temp'
LOG_FILE = '/data/logs/server.log'


class BDSBackup:
    def __init__(self):
        self.api = f"https://api.telegram.org/bot{BOT_TOKEN}"
        self.state = self.load_state()
        self.players = set()
        self.last_activity = time.time()
        self.last_backup = 0
        self.lock = threading.Lock()
        self._stop = False

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    return json.load(f)
            except:
                pass
        return {'backups': [], 'pending_deletions': []}

    def save_state(self):
        with open(STATE_FILE, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_level_name(self):
        try:
            with open('/data/server.properties') as f:
                for line in f:
                    if line.startswith('level-name='):
                        return line.strip().split('=', 1)[1]
        except:
            pass
        return 'Bedrock level'

    def log_watcher(self):
        """Watch BDS logs to track player count"""
        while not self._stop:
            if not os.path.exists(LOG_FILE):
                time.sleep(2)
                continue
            try:
                with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(0, 2)
                    while not self._stop:
                        line = f.readline()
                        if not line:
                            time.sleep(1)
                            continue
                        if 'Player connected:' in line:
                            m = re.search(r'Player connected:\s*(\w+)', line)
                            if m:
                                self.players.add(m.group(1))
                                self.last_activity = time.time()
                                print(f"[Backup] +Player {m.group(1)} | total:{len(self.players)}")
                        elif 'Player disconnected:' in line:
                            m = re.search(r'Player disconnected:\s*(\w+)', line)
                            if m:
                                self.players.discard(m.group(1))
                                self.last_activity = time.time()
                                print(f"[Backup] -Player {m.group(1)} | total:{len(self.players)}")
            except Exception as e:
                print(f"[Backup] Log watcher error: {e}")
                time.sleep(5)

    def should_backup(self):
        if self.players:
            return False
        if time.time() - self.last_activity < IDLE_MINUTES * 60:
            return False
        if time.time() - self.last_backup < BACKUP_INTERVAL:
            return False
        return True

    def compress_world(self, world_path, zip_path):
        print(f"[Backup] Compressing: {world_path}")
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(world_path):
                for file in files:
                    fp = os.path.join(root, file)
                    arcname = os.path.relpath(fp, os.path.dirname(world_path))
                    zf.write(fp, arcname)
        size = os.path.getsize(zip_path)
        print(f"[Backup] Compressed: {size/1024/1024:.1f} MB")
        return size

    def split_file(self, filepath, chunk_dir):
        os.makedirs(chunk_dir, exist_ok=True)
        chunks = []
        with open(filepath, 'rb') as f:
            idx = 0
            while True:
                data = f.read(CHUNK_SIZE)
                if not data:
                    break
                cp = os.path.join(chunk_dir, f"part_{idx:03d}")
                with open(cp, 'wb') as c:
                    c.write(data)
                chunks.append(cp)
                idx += 1
        print(f"[Backup] Split into {len(chunks)} chunks")
        return chunks

    def tg_api(self, method, data=None, files=None, timeout=60):
        url = f"{self.api}/{method}"
        try:
            if files:
                r = requests.post(url, data=data, files=files, timeout=timeout)
            else:
                r = requests.post(url, json=data, timeout=timeout)
            return r.json()
        except Exception as e:
            print(f"[Backup] API error: {e}")
            return {'ok': False}

    def upload_chunk(self, chunk_path, caption):
        with open(chunk_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': CHANNEL_ID, 'caption': caption, 'parse_mode': 'HTML'}
            return self.tg_api('sendDocument', data=data, files=files)

    def send_text(self, text):
        return self.tg_api('sendMessage', data={
            'chat_id': CHANNEL_ID, 'text': text, 'parse_mode': 'HTML'
        })

    def delete_messages(self, message_ids):
        deleted, failed = [], []
        for mid in message_ids:
            res = self.tg_api('deleteMessage', data={
                'chat_id': CHANNEL_ID, 'message_id': mid
            })
            if res.get('ok'):
                deleted.append(mid)
            else:
                failed.append(mid)
            time.sleep(0.5)
        return deleted, failed

    def pin_message(self, message_id):
        return self.tg_api('pinChatMessage', data={
            'chat_id': CHANNEL_ID, 'message_id': message_id
        })

    def unpin_all(self):
        return self.tg_api('unpinAllChatMessages', data={
            'chat_id': CHANNEL_ID
        })

    def get_pinned_message(self):
        res = self.tg_api('getChat', data={'chat_id': CHANNEL_ID})
        if res.get('ok'):
            return res['result'].get('pinned_message')
        return None

    def perform_backup(self):
        with self.lock:
            self.last_backup = time.time()
            level = self.get_level_name()
            world_path = os.path.join('/data/worlds', level)

            if not os.path.exists(world_path):
                print(f"[Backup] World not found: {world_path}")
                return

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            name = f"bds_{timestamp}"
            zip_path = os.path.join(TEMP_DIR, f"{name}.zip")
            chunk_dir = os.path.join(TEMP_DIR, name)

            try:
                self.compress_world(world_path, zip_path)

                with open(zip_path, 'rb') as f:
                    file_hash = hashlib.md5(f.read()).hexdigest()

                chunks = self.split_file(zip_path, chunk_dir)
                total = len(chunks)

                file_ids, msg_ids = [], []
                for i, chunk in enumerate(chunks):
                    caption = (
                        f"📦 <b>BDS Backup Chunk</b>\n"
                        f"Backup: <code>{name}</code>\n"
                        f"Part: {i+1}/{total}\n"
                        f"Level: {level}\n"
                        f"Hash: <code>{file_hash}</code>"
                    )
                    res = self.upload_chunk(chunk, caption)
                    if res.get('ok'):
                        msg_id = res['result']['message_id']
                        file_id = res['result']['document']['file_id']
                        msg_ids.append(msg_id)
                        file_ids.append(file_id)
                        print(f"[Backup] Uploaded {i+1}/{total} msg={msg_id}")
                    else:
                        print(f"[Backup] Upload failed: {res}")
                        self.send_text(f"❌ Backup {name} failed at part {i+1}")
                        return
                    time.sleep(1)

                # Manifest
                manifest_text = (
                    f"📋 <b>BACKUP MANIFEST</b>\n"
                    f"Name: <code>{name}</code>\n"
                    f"Level: {level}\n"
                    f"Parts: {total}\n"
                    f"Hash: <code>{file_hash}</code>\n"
                    f"FileIDs: {','.join(file_ids)}"
                )
                manifest = self.send_text(manifest_text)
                manifest_id = None
                if manifest.get('ok'):
                    manifest_id = manifest['result']['message_id']
                    self.unpin_all()
                    self.pin_message(manifest_id)
                    print(f"[Backup] Manifest pinned: {manifest_id}")

                record = {
                    'name': name,
                    'timestamp': timestamp,
                    'level': level,
                    'parts': total,
                    'msg_ids': msg_ids,
                    'file_ids': file_ids,
                    'manifest_id': manifest_id,
                    'hash': file_hash
                }
                self.state['backups'].append(record)
                self.clean_old_backups()
                self.save_state()

                self.send_text(f"✅ Backup complete: <code>{name}</code> ({total} parts)")
                print(f"[Backup] Complete: {name}")

            finally:
                if os.path.exists(zip_path):
                    os.remove(zip_path)
                if os.path.exists(chunk_dir):
                    shutil.rmtree(chunk_dir)

    def clean_old_backups(self):
        backups = self.state['backups']
        if len(backups) <= 2:
            return

        to_remove = backups[:-2]
        for old in to_remove:
            ids = old.get('msg_ids', []) + ([old['manifest_id']] if old.get('manifest_id') else [])
            deleted, failed = self.delete_messages(ids)

            if failed:
                old['pending_delete'] = True
                old['failed_ids'] = failed
                self.state['pending_deletions'].append(old)
                self.send_text(
                    f"⚠️ <b>Manual Deletion Needed</b>\n"
                    f"Backup: <code>{old['name']}</code>\n"
                    f"Failed IDs: <code>{failed}</code>\n"
                    f"Please delete these messages manually from the channel."
                )

            backups.remove(old)

        self.state['backups'] = backups[-10:]

    def download_file(self, file_id, dest_path):
        res = self.tg_api('getFile', data={'file_id': file_id})
        if not res.get('ok'):
            return False
        file_path = res['result']['file_path']
        url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
        try:
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(dest_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"[Backup] Download error: {e}")
            return False

    def restore_latest(self):
        print("[Restore] Checking for backup...")
        if self.state.get('backups'):
            return self._restore_record(self.state['backups'][-1])

        pinned = self.get_pinned_message()
        if pinned and 'BACKUP MANIFEST' in (pinned.get('text') or ''):
            return self._restore_from_manifest(pinned['text'])

        print("[Restore] No backup found")
        return False

    def _restore_record(self, record):
        name = record['name']
        level = record['level']
        file_ids = record['file_ids']
        expected_hash = record['hash']

        print(f"[Restore] Restoring: {name} ({len(file_ids)} parts)")
        self.send_text(f"🔄 Restoring backup: <code>{name}</code>")

        chunk_dir = os.path.join(TEMP_DIR, 'restore')
        zip_path = os.path.join(TEMP_DIR, 'restore.zip')
        os.makedirs(chunk_dir, exist_ok=True)

        try:
            for i, fid in enumerate(file_ids):
                dest = os.path.join(chunk_dir, f"part_{i:03d}")
                if not self.download_file(fid, dest):
                    print(f"[Restore] Failed part {i}")
                    return False
                print(f"[Restore] Downloaded {i+1}/{len(file_ids)}")

            with open(zip_path, 'wb') as out:
                for i in range(len(file_ids)):
                    part = os.path.join(chunk_dir, f"part_{i:03d}")
                    with open(part, 'rb') as f:
                        out.write(f.read())

            with open(zip_path, 'rb') as f:
                actual_hash = hashlib.md5(f.read()).hexdigest()
            if actual_hash != expected_hash:
                print(f"[Restore] Hash mismatch!")
                return False

            world_dir = os.path.join('/data/worlds', level)
            if os.path.exists(world_dir):
                shutil.move(world_dir, world_dir + '_old_' + str(int(time.time())))

            os.makedirs(world_dir, exist_ok=True)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(os.path.dirname(world_dir))

            print(f"[Restore] Success: {world_dir}")
            self.send_text(f"✅ World restored: <code>{name}</code>")
            return True

        finally:
            if os.path.exists(chunk_dir):
                shutil.rmtree(chunk_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def _restore_from_manifest(self, text):
        m = re.search(r'FileIDs:\s*([\w-_,]+)', text)
        if not m:
            return False
        file_ids = m.group(1).split(',')
        print(f"[Restore] Manifest IDs: {file_ids}")
        # Need hash and level info... fallback
        return False

    def run(self):
        print("[Backup] Service started")
        threading.Thread(target=self.log_watcher, daemon=True).start()
        while not self._stop:
            time.sleep(CHECK_INTERVAL)
            if self.should_backup():
                print("[Backup] Conditions met, starting backup...")
                self.perform_backup()
            else:
                idle = (time.time() - self.last_activity) / 60
                since = (time.time() - self.last_backup) / 60
                print(f"[Backup] Skip | players:{len(self.players)} idle:{idle:.0f}min backup:{since:.0f}min")


def main():
    if not BOT_TOKEN or not CHANNEL_ID:
        print("[Backup] TELEGRAM_BOT_TOKEN and TELEGRAM_CHANNEL_ID required")
        sys.exit(1)

    bot = BDSBackup()
    if len(sys.argv) > 1 and sys.argv[1] == 'restore':
        success = bot.restore_latest()
        sys.exit(0 if success else 1)
    else:
        bot.run()


if __name__ == '__main__':
    main()